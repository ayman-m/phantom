"""Guard: log generation must not consume the faker.unique ledger.

`Events.faker` is a process-wide singleton whose `.unique` ledger is never
reset. Because generation runs once PER EVENT, a generator that used
`faker.unique.first_name()` would permanently consume ~10 entries per event
from a first-name pool of roughly a thousand. After ~100 events the pool
would be exhausted and every subsequent call would raise

    faker.exceptions.UniquenessException: Got duplicated values after 1,000 iterations

for the remaining life of the process. Workers would still report
status=Running and create calls would still return success, so the failure
would be completely silent to the caller.

These tests fail if anyone reintroduces `faker.unique` on a per-event path.
"""

import unittest
import warnings

from app.logforge import Events, Observables
from app.logforge.rfaker import _sample_distinct_names


def _ledger_size():
    """Total entries recorded in the shared faker uniqueness ledger."""
    return sum(len(v) for v in getattr(Events.faker.unique, "_seen", {}).values())


class TestNoUniqueLeak(unittest.TestCase):
    def setUp(self):
        warnings.filterwarnings("ignore", category=UserWarning, module="app.logforge.rfaker")

    def test_per_event_generation_does_not_touch_unique_ledger(self):
        """Generating events must not grow the ledger.

        Uses the same shape as the Sender.send_data loop — count=1 per
        call — because that per-event path is what makes a leak fatal.
        """
        before = _ledger_size()
        observables = Observables(sourceIp=["10.1.1.1", "10.1.1.2"])
        for _ in range(25):
            Events.cef(count=1, observables=observables, vendor="Fortinet", product="FortiGate")
        self.assertEqual(
            _ledger_size(), before,
            "event generation consumed faker.unique entries — the ~100-event "
            "generation cap has been reintroduced",
        )

    def test_generation_survives_well_past_the_old_cap(self):
        """~100 events was the old hard ceiling; 150 must now succeed."""
        observables = Observables(sourceIp=["10.1.1.1"])
        for i in range(150):
            try:
                Events.cef(count=1, observables=observables, vendor="Fortinet", product="FortiGate")
            except Exception as exc:  # pragma: no cover - only on failure
                self.fail(f"generation failed at event {i}: {type(exc).__name__}: {exc}")

    def test_sample_distinct_names_returns_distinct_bounded_list(self):
        names = _sample_distinct_names(Events.faker, 10)
        self.assertLessEqual(len(names), 10)
        self.assertEqual(len(names), len(set(names)), "returned names must be distinct")
        self.assertTrue(all(isinstance(n, str) and n for n in names))

    def test_sample_distinct_names_is_repeatable_without_exhaustion(self):
        """Calling it many times must never raise — the old code eventually did."""
        before = _ledger_size()
        for _ in range(200):
            _sample_distinct_names(Events.faker, 10)
        self.assertEqual(_ledger_size(), before, "helper must not use faker.unique")



class TestObservableSourceCaching(unittest.TestCase):
    """Threat-intel source lists must be fetched once, not per event.

    Fetching on every field generation would cost six requests per event
    (~94ms each) — most of the generation time spent re-downloading identical
    static lists, and a hard runtime dependency on GitHub being reachable
    mid-run. `_get_observables_from_source` caches the fetched lists.
    """

    def test_source_fetches_are_cached_not_repeated(self):
        from unittest.mock import patch
        from app.logforge import rfaker

        rfaker._OBSERVABLE_SOURCE_CACHE.clear()

        class _Resp:
            status_code = 200
            text = "1.2.3.4\n5.6.7.8\n9.10.11.12\n"

        source = {"type": "ip", "url": "https://example.invalid/bad-ip.txt", "structure": "lines"}

        with patch.object(rfaker.requests, "get", return_value=_Resp()) as mock_get:
            for _ in range(25):
                rfaker.Observables._get_observables_from_source(source)
            self.assertEqual(
                mock_get.call_count, 1,
                f"expected exactly 1 network fetch for 25 calls, got {mock_get.call_count} — "
                "per-event refetching has returned",
            )

    def test_cache_is_not_mutated_by_callers(self):
        """The cached list must survive a caller shuffling its copy."""
        from unittest.mock import patch
        from app.logforge import rfaker

        rfaker._OBSERVABLE_SOURCE_CACHE.clear()

        class _Resp:
            status_code = 200
            text = "\n".join(f"10.0.0.{i}" for i in range(50))

        source = {"type": "ip", "url": "https://example.invalid/x.txt", "structure": "lines"}
        with patch.object(rfaker.requests, "get", return_value=_Resp()):
            first = rfaker.Observables._get_observables_from_source(source)
            second = rfaker.Observables._get_observables_from_source(source)
        self.assertEqual(sorted(first), sorted(second), "cache returned a different value set")
        self.assertEqual(len(first), 50)

if __name__ == "__main__":
    unittest.main()
