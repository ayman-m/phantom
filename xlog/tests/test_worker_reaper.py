"""A wedged worker must not hold capacity forever — and a slow one must live.

A worker can stop making progress without exiting: blocked in a socket send
to a dead destination, or its thread dead on an uncaught exception. The
registry keeps counting it either way, so it holds a population slot AND its
declared rate against the aggregate ceiling — admission then refuses NEW
workers on behalf of one doing nothing. In-loop checks cannot help; the loop
is not running.

The dangerous half is the false positive. A 0.2 ev/s baseline worker emits
once every five seconds BY DESIGN. Reaping it would be worse than the leak.
"""

import threading
import time
import unittest

from app.config import Config
from app.worker_registry import WorkerRegistry, reap_once


class _Sender:
    def __init__(self, name, alive=True, started=True, interval=5, status="Running"):
        self.worker_name = name
        self.status = status
        self.interval = interval
        self.count = 1
        self.events_per_second = 1.0 / interval
        self._last_report_at = time.monotonic()
        self._thread = threading.Thread(target=lambda: None)
        if started:
            self._thread.start()
            if alive:
                # Keep it alive for the duration of the test.
                self._thread = threading.Thread(target=lambda: time.sleep(30), daemon=True)
                self._thread.start()
            else:
                self._thread.join()

    def start(self): pass
    def stop(self): self.status = "Stopped"; return self.status


def _registry(**over):
    for k, v in {"XLOG_MAX_WORKER_EVENTS_PER_SEC": "0",
                 "XLOG_MAX_TOTAL_EVENTS_PER_SEC": "0",
                 "WORKERS_NUMBER": "50",
                 "XLOG_REAPER_STALL_SECONDS": "0"}.items():
        setattr(Config, k, over.get(k, v))
    for k, v in over.items():
        setattr(Config, k, v)
    return WorkerRegistry()


class TestDetectorA(unittest.TestCase):
    """Dead thread + status Running. Unambiguous, always on."""

    def test_dead_thread_is_reaped(self):
        r = _registry()
        r.admit([_Sender("dead", alive=False)])
        out = reap_once(r)
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["reaped"][0]["reason"], "thread_dead")
        self.assertEqual(r.names(), [])

    def test_live_worker_is_left_alone(self):
        r = _registry()
        r.admit([_Sender("live", alive=True)])
        self.assertEqual(reap_once(r)["count"], 0)
        self.assertEqual(len(r.names()), 1)

    def test_never_started_thread_is_not_reaped(self):
        """Every sender sets status=Running BEFORE thread.start().

        Without the ident guard the reaper would kill workers microseconds
        old, in the window between those two statements.
        """
        r = _registry()
        r.admit([_Sender("newborn", started=False)])
        self.assertEqual(reap_once(r)["count"], 0)

    def test_already_stopped_worker_is_not_double_reaped(self):
        r = _registry()
        r.admit([_Sender("done", alive=False, status="Stopped")])
        self.assertEqual(reap_once(r)["count"], 0)


class TestDetectorB(unittest.TestCase):
    """Stall detection is opt-in, and must never reap a merely-slow worker."""

    def test_disabled_by_default(self):
        r = _registry()
        s = _Sender("slow", alive=True, interval=5)
        s._last_report_at = time.monotonic() - 3600  # an hour of silence
        r.admit([s])
        self.assertEqual(reap_once(r)["count"], 0,
                         "stall detection must be off unless configured")

    def test_slow_worker_survives_even_when_enabled(self):
        """0.2 ev/s emits once per 5s by design — not a stall."""
        r = _registry(XLOG_REAPER_STALL_SECONDS="30")
        s = _Sender("baseline", alive=True, interval=5)
        s._last_report_at = time.monotonic() - 40  # > floor, < 20x interval
        r.admit([s])
        self.assertEqual(reap_once(r)["count"], 0)

    def test_genuinely_stalled_worker_is_reaped_when_enabled(self):
        r = _registry(XLOG_REAPER_STALL_SECONDS="30")
        s = _Sender("wedged", alive=True, interval=5)
        s._last_report_at = time.monotonic() - 600  # way past 20x interval
        r.admit([s])
        out = reap_once(r)
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["reaped"][0]["reason"], "stalled")

    def test_threshold_scales_with_the_workers_own_interval(self):
        """A 60s-interval worker must get a proportionally longer grace."""
        r = _registry(XLOG_REAPER_STALL_SECONDS="30")
        s = _Sender("infrequent", alive=True, interval=60)
        s._last_report_at = time.monotonic() - 600  # < 20 * 60
        r.admit([s])
        self.assertEqual(reap_once(r)["count"], 0)


class TestReclamation(unittest.TestCase):
    def test_reaping_frees_capacity_for_a_new_worker(self):
        """The whole point: a wedged worker must stop blocking admission."""
        r = _registry(WORKERS_NUMBER="1")
        r.admit([_Sender("hog", alive=False)])
        reap_once(r)
        self.assertEqual(len(r.admit([_Sender("fresh", alive=True)])), 1)


if __name__ == "__main__":
    unittest.main()
