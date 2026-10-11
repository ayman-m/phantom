"""OverrideSender must not emit silently.

The legacy Sender logs a line per event ("sending log message"); anything
monitoring throughput with `docker logs xlog | grep -c "sending log message"`
would under-report by exactly however much the schema_override path emits if
OverrideSender stayed silent — a worker doing 200 events/sec would look
identical to an idle one. (A `count=200, interval=1` worker runs at 200
events/SECOND, since count is per-tick here and the worker runs until stopped.)

These tests pin the properties that keep it observable:
  1. the sustained rate is stated up front, in events/sec and per-day
  2. high rates are flagged loudly
  3. the periodic line reuses the legacy Sender wording so ONE grep covers both
     sender paths
  4. a non-positive interval is refused rather than silently unthrottled
  5. a worker that ends on its own reports that it ended — otherwise the
     registry never reclaims its rate or its burst slot
"""

import io
import logging
import unittest

from app.override_sender import OverrideSender


def _sender(count, interval):
    return OverrideSender(
        worker_name=f"test-w-{count}-{interval}",
        data_type="CEF",
        destination="udp:10.0.0.1:514",
        vendor_fields=[],
        count=count,
        interval=interval,
        vendor="Fortinet",
        product="FortiGate",
    )


class _CaptureLogs:
    def __enter__(self):
        self.buf = io.StringIO()
        self.handler = logging.StreamHandler(self.buf)
        self.handler.setFormatter(logging.Formatter("%(message)s"))
        self.logger = logging.getLogger("xlog.override_sender")
        self._prev_level = self.logger.level
        self.logger.addHandler(self.handler)
        self.logger.setLevel(logging.INFO)
        return self

    def __exit__(self, *exc):
        self.logger.removeHandler(self.handler)
        self.logger.setLevel(self._prev_level)
        return False

    @property
    def text(self):
        return self.buf.getvalue()


class TestOverrideSenderObservability(unittest.TestCase):
    def test_startup_states_sustained_rate_not_just_count(self):
        """`count` alone is misleading — the log must state events/sec."""
        with _CaptureLogs() as cap:
            _sender(count=200, interval=1)._log_startup_rate()
        self.assertIn("200.00 events/sec", cap.text)
        self.assertIn("17,280,000/day", cap.text)
        self.assertIn("sustained until stopped", cap.text)

    def test_high_rate_is_flagged(self):
        with _CaptureLogs() as cap:
            _sender(count=200, interval=1)._log_startup_rate()
        self.assertIn("HIGH RATE", cap.text)

    def test_modest_rate_is_not_flagged(self):
        with _CaptureLogs() as cap:
            _sender(count=1, interval=5)._log_startup_rate()
        self.assertIn("0.20 events/sec", cap.text)
        self.assertNotIn("HIGH RATE", cap.text)

    def test_startup_line_survives_formatting(self):
        """'%,.0f' is f-string syntax and raises inside %-style
        logging, which logging swallows — silently dropping this very line."""
        with _CaptureLogs() as cap:
            _sender(count=7, interval=3)._log_startup_rate()
        self.assertIn("OverrideSender", cap.text)
        self.assertNotIn("--- Logging error ---", cap.text)

    def test_periodic_line_matches_legacy_sender_wording(self):
        """One grep must cover BOTH sender paths, so the phrasing is shared."""
        import inspect
        from app import override_sender

        src = inspect.getsource(override_sender.OverrideSender._run)
        self.assertIn(
            "sending log message", src,
            "periodic throughput line must reuse the legacy Sender wording so "
            "`grep -c 'sending log message'` counts this path too",
        )

    def test_emission_counter_initialised(self):
        s = _sender(count=1, interval=5)
        self.assertEqual(s._sent_total, 0)


class TestOverrideSenderRejectsUnthrottled(unittest.TestCase):
    """`interval <= 0` is refused at construction.

    It is not merely invalid input — it is the HIGHEST-output configuration
    this class can accept. The tick loop throttles with
    `self._stop_event.wait(self.interval)`, and Event.wait() returns
    immediately for both 0 and negative values, so the loop spins as fast as
    the CPU allows.

    A negative interval was doubly dangerous: `count / interval` went negative,
    so the `per_sec > 10` high-rate check passed it silently. The most
    dangerous input produced the least warning.
    """

    def test_zero_interval_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            _sender(count=5, interval=0)
        self.assertIn("interval must be >= 1", str(ctx.exception))

    def test_negative_interval_rejected(self):
        """The case that defeated the high-rate warning entirely."""
        with self.assertRaises(ValueError) as ctx:
            _sender(count=200, interval=-1)
        self.assertIn("interval must be >= 1", str(ctx.exception))

    def test_zero_and_negative_count_rejected(self):
        for bad in (0, -5):
            with self.assertRaises(ValueError) as ctx:
                _sender(count=bad, interval=5)
            self.assertIn("count must be >= 1", str(ctx.exception))

    def test_error_explains_why_rather_than_just_refusing(self):
        """An agent reads the message to correct itself; it must say WHY."""
        with self.assertRaises(ValueError) as ctx:
            _sender(count=1, interval=0)
        msg = str(ctx.exception)
        self.assertIn("does not throttle", msg)

    def test_smallest_valid_interval_still_accepted(self):
        """The guard must not over-reject: interval=1 is legitimate."""
        s = _sender(count=1, interval=1)
        self.assertEqual(s.interval, 1)


class TestSelfTerminationIsReported(unittest.TestCase):
    """A worker that ends on its own must SAY it ended.

    If only stop() wrote `status`, a burst that exhausted its budget would
    keep reporting "Running" forever. The registry reclaims rate by pruning
    non-Running workers, so a finished burst would keep consuming the aggregate
    ceiling and holding its burst-concurrency slot until the container
    restarted — one completed burst would block every later one.
    """

    def test_budget_exhaustion_marks_the_worker_stopped(self):
        s = OverrideSender(
            worker_name="budget-probe",
            data_type="CEF",
            destination="udp:127.0.0.1:9",   # discard port; nothing listens
            vendor_fields=[{"name": "src"}],
            count=5,
            interval=1,
            vendor="Fortinet",
            product="FortiGate",
            max_events=5,
        )
        s.start()
        s._thread.join(timeout=10)
        self.assertFalse(s._thread.is_alive(), "worker should have self-terminated")
        self.assertEqual(s.status, "Stopped")
        self.assertGreaterEqual(s._sent_total, 5)

    def test_budget_is_declared_as_a_real_bound(self):
        s = OverrideSender(
            worker_name="b", data_type="CEF", destination="udp:127.0.0.1:9",
            vendor_fields=[{"name": "src"}], count=50, interval=1,
            vendor="F", product="G", max_events=150,
        )
        self.assertEqual(s.max_total_events, 150)

    def test_no_budget_means_unbounded(self):
        s = OverrideSender(
            worker_name="u", data_type="CEF", destination="udp:127.0.0.1:9",
            vendor_fields=[{"name": "src"}], count=50, interval=1,
            vendor="F", product="G",
        )
        self.assertIsNone(s.max_total_events)


if __name__ == "__main__":
    unittest.main()
