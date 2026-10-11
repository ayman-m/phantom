"""Admission control for log-generation workers.

These pin the admission ceilings: a worker created with count=200, interval=1
runs at 200 events/SECOND (not "200 events"), which is ~720k events an hour,
so the (count, interval) pair must be validated against a rate ceiling, not
just a worker-count ceiling.

The subtle part is that `count` means
opposite things on the two sender paths — so admission must ask each sender
for its own rate rather than compute one from the request arguments.
"""

import unittest

from app.config import Config
from app.worker_registry import (
    WorkerAdmissionError,
    WorkerRegistry,
    events_per_second,
    rate_from,
)


class _FakeSender:
    """Minimal stand-in exposing the registry's expected surface."""

    def __init__(self, rate, status="Running", name="w"):
        self._rate = rate
        self.status = status
        self.worker_name = name
        self.started = False

    @property
    def events_per_second(self):
        return self._rate

    def start(self):
        self.started = True

    def stop(self):
        self.status = "Stopped"
        return self.status


class _RatelessSender:
    """A sender that forgot to declare events_per_second."""

    def __init__(self, count, interval):
        self.count = count
        self.interval = interval
        self.status = "Running"
        self.worker_name = "rateless"


def _registry(**overrides):
    """Registry with ceilings pinned, independent of the environment."""
    defaults = {
        "XLOG_MAX_WORKER_EVENTS_PER_SEC": "10",
        "XLOG_MAX_BURST_EVENTS_PER_SEC": "500",
        "XLOG_MAX_BURST_EVENTS": "50000",
        "XLOG_MAX_CONCURRENT_BURSTS": "1",
        "XLOG_MAX_TOTAL_EVENTS_PER_SEC": "50",
        "WORKERS_NUMBER": "25",
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(Config, k, v)
    return WorkerRegistry()


class TestRateArithmetic(unittest.TestCase):
    def test_non_positive_interval_is_unbounded_not_a_small_number(self):
        """interval<=0 does not throttle at all, so it must price as inf.

        Reading it as a plain division is how a NEGATIVE interval slipped
        past a `> ceiling` check: -200 is not greater than 10.
        """
        self.assertEqual(rate_from(200, 0), float("inf"))
        self.assertEqual(rate_from(200, -1), float("inf"))
        self.assertEqual(rate_from(200, 1), 200.0)

    def test_unknown_sender_class_fails_closed(self):
        """A sender with no events_per_second must not read as free."""

        class Mystery:
            status = "Running"

        self.assertEqual(events_per_second(Mystery()), float("inf"))

    def test_falls_back_to_count_over_interval(self):
        self.assertEqual(events_per_second(_RatelessSender(20, 4)), 5.0)


class TestPerWorkerCeiling(unittest.TestCase):
    def test_the_high_rate_configuration_is_refused(self):
        """count=200, interval=1 on the override path: 200 ev/s."""
        r = _registry()
        with self.assertRaises(WorkerAdmissionError) as ctx:
            r.admit([_FakeSender(200.0)])
        msg = str(ctx.exception)
        self.assertIn("200.00 events/sec", msg)
        self.assertIn("ceiling of 10", msg)

    def test_rejection_explains_the_burst_escape_hatch(self):
        """The caller is often an agent; the error must teach the fix."""
        r = _registry()
        with self.assertRaises(WorkerAdmissionError) as ctx:
            r.admit([_FakeSender(200.0)])
        self.assertIn("duration_seconds", str(ctx.exception))

    def test_intended_steady_state_is_accepted(self):
        """The guard must not break normal use: ~0.5 ev/s baseline."""
        r = _registry()
        names = r.admit([_FakeSender(0.2), _FakeSender(0.17)])
        self.assertEqual(len(names), 2)

    def test_rejected_worker_is_not_registered(self):
        r = _registry()
        with self.assertRaises(WorkerAdmissionError):
            r.admit([_FakeSender(999.0)])
        self.assertEqual(r.names(), [])

    def test_unbounded_interval_refused(self):
        r = _registry()
        with self.assertRaises(WorkerAdmissionError) as ctx:
            r.admit([_RatelessSender(10, 0)])
        self.assertIn("unbounded", str(ctx.exception))


class TestBurstAllowance(unittest.TestCase):
    """Bursts carry a REAL budget (_BoundedSender), never just a claim.

    These originally used a sender with no budget plus bounded=[True], which
    is exactly the shape that shipped the unbounded-burst bug — see
    TestPromiseMustReachTheWorker. A burst is only a burst if the worker
    itself reports a limit.
    """

    def test_declared_burst_may_exceed_the_sustained_ceiling(self):
        """Phantom's purpose is volume; a bounded burst must still work."""
        r = _registry()
        names = r.admit([_BoundedSender(total=1500, rate=200.0)], bounded=[True])
        self.assertEqual(len(names), 1)

    def test_burst_still_has_its_own_ceiling(self):
        r = _registry()
        with self.assertRaises(WorkerAdmissionError) as ctx:
            r.admit([_BoundedSender(total=1500, rate=900.0)], bounded=[True])
        self.assertIn("burst ceiling of 500", str(ctx.exception))

    def test_concurrent_bursts_are_limited(self):
        r = _registry()
        r.admit([_BoundedSender(total=1500, rate=200.0)], bounded=[True])
        with self.assertRaises(WorkerAdmissionError) as ctx:
            r.admit([_BoundedSender(total=1500, rate=200.0)], bounded=[True])
        self.assertIn("already running", str(ctx.exception))

    def test_burst_is_not_summed_into_the_sustained_aggregate(self):
        """Otherwise one burst would lock out every ordinary worker."""
        r = _registry()
        r.admit([_BoundedSender(total=1500, rate=400.0)], bounded=[True])
        names = r.admit([_FakeSender(5.0)])
        self.assertEqual(len(names), 1)


class TestAggregateCeiling(unittest.TestCase):
    def test_many_legal_workers_still_hit_the_aggregate(self):
        """The gap WORKERS_NUMBER left open: 25 x 200/sec passed it."""
        r = _registry()
        for _ in range(5):
            r.admit([_FakeSender(10.0)])
        with self.assertRaises(WorkerAdmissionError) as ctx:
            r.admit([_FakeSender(10.0)])
        self.assertIn("aggregate ceiling of 50", str(ctx.exception))

    def test_aggregate_error_names_the_biggest_consumers(self):
        r = _registry()
        for _ in range(5):
            r.admit([_FakeSender(10.0)])
        with self.assertRaises(WorkerAdmissionError) as ctx:
            r.admit([_FakeSender(10.0)])
        self.assertIn("largest:", str(ctx.exception))

    def test_stopped_workers_release_their_rate(self):
        r = _registry()
        names = [r.admit([_FakeSender(10.0)])[0] for _ in range(5)]
        r.get(names[0]).status = "Stopped"
        self.assertEqual(len(r.admit([_FakeSender(10.0)])), 1)


class TestPopulationCeiling(unittest.TestCase):
    def test_batch_counted_as_a_whole_not_per_insert(self):
        """The scenario bug: cap checked once, then inserted in a loop."""
        r = _registry(WORKERS_NUMBER="4", XLOG_MAX_TOTAL_EVENTS_PER_SEC="0")
        r.admit([_FakeSender(0.1), _FakeSender(0.1), _FakeSender(0.1)])
        with self.assertRaises(WorkerAdmissionError) as ctx:
            r.admit([_FakeSender(0.1), _FakeSender(0.1)])
        self.assertIn("only 1 slot", str(ctx.exception))

    def test_batch_admission_is_all_or_nothing(self):
        r = _registry(WORKERS_NUMBER="2", XLOG_MAX_TOTAL_EVENTS_PER_SEC="0")
        with self.assertRaises(WorkerAdmissionError):
            r.admit([_FakeSender(0.1), _FakeSender(0.1), _FakeSender(0.1)])
        self.assertEqual(r.names(), [])


class TestNameUniqueness(unittest.TestCase):
    def test_same_second_workers_do_not_collide(self):
        """Names were minted at second resolution with no suffix.

        A collision silently overwrote an ALREADY-STARTED worker, orphaning
        its thread: invisible to list_workers, unreachable by kill_worker,
        and uncounted against every ceiling.
        """
        r = _registry(XLOG_MAX_TOTAL_EVENTS_PER_SEC="0")
        names = r.admit([_FakeSender(0.1) for _ in range(10)])
        self.assertEqual(len(set(names)), 10)
        self.assertEqual(len(r.names()), 10)

    def test_admitted_sender_carries_its_assigned_name(self):
        r = _registry()
        s = _FakeSender(0.1)
        name = r.admit([s])[0]
        self.assertEqual(s.worker_name, name)


class TestDisablingCeilings(unittest.TestCase):
    def test_zero_disables_a_ceiling(self):
        r = _registry(
            XLOG_MAX_WORKER_EVENTS_PER_SEC="0",
            XLOG_MAX_TOTAL_EVENTS_PER_SEC="0",
        )
        self.assertEqual(len(r.admit([_FakeSender(5000.0)])), 1)

    def test_malformed_ceiling_falls_back_rather_than_uncapping(self):
        """Garbage config must not silently mean 'unlimited'."""
        r = _registry(XLOG_MAX_WORKER_EVENTS_PER_SEC="not-a-number")
        with self.assertRaises(WorkerAdmissionError):
            r.admit([_FakeSender(200.0)])


class TestStopPath(unittest.TestCase):
    def test_stop_marks_and_pop_removes(self):
        r = _registry()
        name = r.admit([_FakeSender(0.2)])[0]
        r.stop(name)
        r.pop(name)
        self.assertEqual(r.names(), [])

    def test_snapshot_reports_ceilings_and_consumption(self):
        r = _registry()
        r.admit([_FakeSender(2.0)])
        snap = r.snapshot()
        self.assertAlmostEqual(snap["sustained_events_per_second"], 2.0)
        self.assertEqual(snap["ceilings"]["worker_eps"], 10)


if __name__ == "__main__":
    unittest.main()


class _BoundedSender:
    """A sender bounded by construction, like the legacy Sender."""

    def __init__(self, total, rate, name="b"):
        self._total = total
        self._rate = rate
        self.status = "Running"
        self.worker_name = name

    @property
    def max_total_events(self):
        return self._total

    @property
    def events_per_second(self):
        return self._rate

    def stop(self):
        self.status = "Stopped"
        return self.status


class TestBoundedWorkersArePricedByTotal(unittest.TestCase):
    """A worker that cannot run away must be judged on volume, not rate.

    The legacy Sender delivers exactly `count` events and stops. Capping its
    RATE would refuse harmless work — the bootstrap_dataset_fields skill fires
    one 100-event worker per installed data source — while doing nothing for
    safety, because the total is already fixed. Only an UNBOUNDED worker's
    rate is dangerous, since its eventual volume is rate x forever.
    """

    def test_bounded_run_above_the_sustained_ceiling_is_allowed(self):
        r = _registry()
        self.assertEqual(len(r.admit([_BoundedSender(total=100, rate=50.0)])), 1)

    def test_bounded_run_still_capped_on_total(self):
        r = _registry()
        with self.assertRaises(WorkerAdmissionError) as ctx:
            r.admit([_BoundedSender(total=5_000_000, rate=1.0)])
        self.assertIn("exceeds the", str(ctx.exception))

    def test_the_bootstrap_skill_shape_is_admitted(self):
        """11 parallel sources, 100 events each at 1/sec."""
        r = _registry()
        names = r.admit([_BoundedSender(total=100, rate=1.0) for _ in range(11)])
        self.assertEqual(len(names), 11)

    def test_slow_bounded_worker_does_not_consume_a_burst_grant(self):
        """Otherwise concurrent-burst=1 would serialize ordinary work."""
        r = _registry()
        r.admit([_BoundedSender(total=100, rate=1.0) for _ in range(3)])
        self.assertEqual(r.snapshot()["concurrent_bursts"], 0)

    def test_unbounded_worker_is_still_judged_on_rate(self):
        """The high-rate case must stay refused."""
        r = _registry()
        with self.assertRaises(WorkerAdmissionError) as ctx:
            r.admit([_FakeSender(200.0)])
        self.assertIn("never stops on its own", str(ctx.exception))


class TestPromiseMustReachTheWorker(unittest.TestCase):
    """A burst claim in the REQUEST is not a bound on the WORKER.

    Shipped bug, caught only on the live install: the resolver computed
    "this is a burst" from the request but never passed the budget into the
    sender's constructor. Admission granted 200 events/sec on the strength of
    a promise the worker had never received, and it ran unbounded until it
    was killed by hand.

    The lesson is structural, not a one-line fix: boundedness must be read
    off the SENDER, so a budget that fails to arrive is refused rather than
    silently granting the privileged rate.
    """

    def test_declared_burst_without_a_real_budget_is_refused(self):
        r = _registry()
        unbounded_but_claimed = _FakeSender(200.0)  # no max_total_events
        with self.assertRaises(WorkerAdmissionError) as ctx:
            r.admit([unbounded_but_claimed], bounded=[True])
        self.assertIn("did not reach it", str(ctx.exception))

    def test_the_error_blames_the_code_not_the_caller(self):
        """The caller did nothing wrong; the message must say so."""
        r = _registry()
        with self.assertRaises(WorkerAdmissionError) as ctx:
            r.admit([_FakeSender(200.0)], bounded=[True])
        self.assertIn("bug in the worker-creation path", str(ctx.exception))

    def test_a_real_budget_still_earns_the_burst_ceiling(self):
        r = _registry()
        self.assertEqual(
            len(r.admit([_BoundedSender(total=1500, rate=200.0)], bounded=[True])), 1
        )


class TestSnapshotIsJsonSafe(unittest.TestCase):
    """A UI consumer must be able to JSON.parse the snapshot.

    snapshot() can carry float('inf') — rate_from returns it for a
    non-positive interval, events_per_second for a sender declaring no rate.
    Python's json.dumps writes that as the bare token `Infinity`, which is not
    in the JSON grammar, so a browser's JSON.parse rejects the ENTIRE document.
    The panel would die with a parse error rather than showing the one worker
    that most needs showing — the unbounded one.
    """

    def test_unbounded_worker_does_not_break_json(self):
        import json

        class _Mystery:            # no events_per_second -> priced as inf
            status = "Running"
            worker_name = "m"
            def stop(self): self.status = "Stopped"; return self.status

        r = _registry(
            XLOG_MAX_WORKER_EVENTS_PER_SEC="0",
            XLOG_MAX_TOTAL_EVENTS_PER_SEC="0",
        )
        r.admit([_Mystery()])

        raw = json.dumps(r.snapshot_json())
        self.assertNotIn("Infinity", raw)
        # Strict parse, the way JSON.parse behaves.
        json.loads(raw, parse_constant=lambda c: (_ for _ in ()).throw(
            AssertionError(f"bare token {c!r} leaked into JSON")))

    def test_unbounded_is_flagged_not_just_nulled(self):
        class _Mystery:
            status = "Running"
            worker_name = "m"
            def stop(self): self.status = "Stopped"; return self.status

        r = _registry(
            XLOG_MAX_WORKER_EVENTS_PER_SEC="0",
            XLOG_MAX_TOTAL_EVENTS_PER_SEC="0",
        )
        r.admit([_Mystery()])
        w = r.snapshot_json()["workers"][0]
        self.assertIsNone(w["events_per_second"])
        self.assertTrue(w["events_per_second_unbounded"])

    def test_ordinary_worker_reports_a_number(self):
        r = _registry()
        r.admit([_FakeSender(2.5)])
        w = r.snapshot_json()["workers"][0]
        self.assertEqual(w["events_per_second"], 2.5)
        self.assertFalse(w["events_per_second_unbounded"])

    def test_ceilings_travel_with_the_snapshot(self):
        """The panel shows rate AGAINST a ceiling; both come from one call."""
        r = _registry()
        snap = r.snapshot_json()
        self.assertEqual(snap["ceilings"]["worker_eps"], 10)
        self.assertEqual(snap["ceilings"]["total_eps"], 50)
