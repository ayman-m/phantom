"""An xlog restart must not silently end all log generation.

Workers live in a module-level registry, so without persistence a restart
would drop every one of them: `list_workers` would return empty and the
platform would look idle rather than broken. That is worse than a crash — the
telemetry feeds detector baselining, and that clock only advances while data
is arriving, so a silent stop sets back the one thing that cannot be
recovered later.

These pin the persistence contract and, in particular, the budget rule: a
restored bounded worker must NEVER replay its full budget, or a crash loop
becomes an amplifier.
"""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("XLOG_DB_PATH", str(Path(tempfile.mkdtemp()) / "t.db"))

from app import store  # noqa: E402


class TestWorkerSpecPersistence(unittest.TestCase):
    def setUp(self):
        store.DB_PATH = Path(tempfile.mkdtemp()) / "t.db"
        store.init_db()

    def test_spec_round_trips(self):
        spec = {"type": "CEF", "destination": "udp:10.0.0.1:514", "count": 1,
                "interval": 6, "vendor": "Fortinet", "product": "FortiGate"}
        store.save_worker_spec("w1", spec)
        rows = store.list_worker_specs()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["worker_name"], "w1")
        self.assertEqual(rows[0]["spec"]["vendor"], "Fortinet")

    def test_stopping_a_worker_removes_its_row(self):
        """Otherwise a restart resurrects workers the operator killed."""
        store.save_worker_spec("w1", {"count": 1})
        store.delete_worker_spec("w1")
        self.assertEqual(store.list_worker_specs(), [])

    def test_progress_checkpoint_is_recorded(self):
        store.save_worker_spec("w1", {"count": 1, "max_events": 1000})
        store.update_worker_progress("w1", 400)
        self.assertEqual(store.list_worker_specs()[0]["events_sent"], 400)

    def test_remaining_budget_is_what_survives_a_restart(self):
        """The rule that stops a crash loop becoming an amplifier.

        A 1000-event burst that already sent 400 must resume with 600, not
        1000 — otherwise every restart replays the whole budget.
        """
        store.save_worker_spec("w1", {"max_events": 1000})
        store.update_worker_progress("w1", 400)
        row = store.list_worker_specs()[0]
        remaining = int(row["spec"]["max_events"]) - int(row["events_sent"])
        self.assertEqual(remaining, 600)

    def test_exhausted_budget_yields_nothing_to_restore(self):
        store.save_worker_spec("w1", {"max_events": 500})
        store.update_worker_progress("w1", 500)
        row = store.list_worker_specs()[0]
        self.assertLessEqual(
            int(row["spec"]["max_events"]) - int(row["events_sent"]), 0
        )

    def test_resaving_updates_rather_than_duplicates(self):
        store.save_worker_spec("w1", {"count": 1})
        store.save_worker_spec("w1", {"count": 9})
        rows = store.list_worker_specs()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["spec"]["count"], 9)

    def test_empty_table_means_nothing_was_running(self):
        """A non-empty table at boot is the signal that workers were lost."""
        self.assertEqual(store.list_worker_specs(), [])


if __name__ == "__main__":
    unittest.main()


class TestRestoreDoesNotMultiply(unittest.TestCase):
    """Restore must be idempotent across repeated restarts.

    Found live: after three restarts the install was running 8 workers where
    4 were configured, at DOUBLE the intended generation rate, with 12
    persisted rows — three copies of each worker.

    Cause: restore re-saved the spec under the newly-minted name while the
    spec body still carried the ORIGINAL name. The next boot's delete keyed
    off one and the row off the other, so nothing was ever removed and every
    restart restored the stale rows too.

    On a live tenant that is the failure this whole feature exists to
    prevent, in reverse: instead of losing generation, it silently
    multiplies it.
    """

    def setUp(self):
        store.DB_PATH = Path(tempfile.mkdtemp()) / "t.db"
        store.init_db()

    def _spec(self, vendor, product, interval):
        return {"destination": "udp:10.0.0.1:514", "vendor": vendor,
                "product": product, "count": 1, "interval": interval,
                "schema_override": [{"name": "src", "type": "string"}]}

    def test_duplicate_rows_collapse_to_one_stream(self):
        """Identity is what the worker DOES, not the name it was given."""
        for i, nm in enumerate(["w1", "w2", "w3"]):
            store.save_worker_spec(nm, self._spec("Fortinet", "FortiGate", 6))
        rows = store.list_worker_specs()
        self.assertEqual(len(rows), 3, "three rows describe the SAME stream")

        seen, restorable = set(), []
        for r in rows:
            sp = r["spec"]
            ident = (sp.get("destination"), sp.get("vendor"),
                     sp.get("product"), sp.get("count"), sp.get("interval"))
            if ident in seen:
                continue
            seen.add(ident)
            restorable.append(r)
        self.assertEqual(len(restorable), 1,
                         "duplicates must restore once, not three times")

    def test_genuinely_distinct_workers_are_all_restored(self):
        """The dedupe must not collapse workers that differ."""
        store.save_worker_spec("a", self._spec("Fortinet", "FortiGate", 6))
        store.save_worker_spec("b", self._spec("Fortinet", "FortiWeb", 7))
        store.save_worker_spec("c", self._spec("Zscaler", "ZPA", 8))
        seen = set()
        for r in store.list_worker_specs():
            sp = r["spec"]
            seen.add((sp.get("destination"), sp.get("vendor"),
                      sp.get("product"), sp.get("count"), sp.get("interval")))
        self.assertEqual(len(seen), 3, "distinct streams must all survive")

    def test_same_vendor_different_interval_is_distinct(self):
        """Interval is part of identity — same vendor at another rate differs."""
        store.save_worker_spec("a", self._spec("Fortinet", "FortiGate", 6))
        store.save_worker_spec("b", self._spec("Fortinet", "FortiGate", 30))
        seen = set()
        for r in store.list_worker_specs():
            sp = r["spec"]
            seen.add((sp.get("destination"), sp.get("vendor"),
                      sp.get("product"), sp.get("count"), sp.get("interval")))
        self.assertEqual(len(seen), 2)


class TestSchemaOverrideIsSerialisable(unittest.TestCase):
    """A schema-driven worker's spec must survive json encoding.

    _persist_spec must not store the Strawberry SchemaOverrideField
    objects directly. save_worker_spec json-encodes the spec, so storing them
    would make EVERY schema-override worker raise

        TypeError: Object of type SchemaOverrideField is not JSON serializable

    and its spec was never written. The failure was caught and logged as a
    warning — deliberately, so a store failure cannot kill a healthy worker —
    which meant restore_workers_on_boot silently had nothing to restore for
    exactly the workers that matter. This test covers it, since the failure
    is otherwise visible only in the container log.
    """

    def setUp(self):
        store.DB_PATH = Path(tempfile.mkdtemp()) / "t.db"
        store.init_db()

    def test_strawberry_field_objects_survive_persistence(self):
        import json

        from app.override_sender import _field_to_dict

        class _Field:  # stands in for the Strawberry input object
            name = "src"
            type = "ipv4"
            is_gate = True
            example = "10.20.0.1"
            enum_values = None
            is_array = False
            is_meta = False

        spec = {
            "worker_name": "w1",
            "type": "CEF",
            "destination": "udp:10.0.0.27:5514",
            "schema_override": [_field_to_dict(_Field())],
        }
        # the operation that would raise on raw Strawberry objects
        json.dumps(spec)

        store.save_worker_spec("w1", spec)
        rows = {r["worker_name"]: r for r in store.list_worker_specs()}
        self.assertIn("w1", rows)
        field = rows["w1"]["spec"]["schema_override"][0]
        self.assertEqual(field["name"], "src")
        self.assertEqual(field["example"], "10.20.0.1")
        self.assertTrue(field["is_gate"])

    def test_dicts_round_trip_unchanged(self):
        """A restored worker re-persists without degrading."""
        from app.override_sender import _field_to_dict

        self.assertEqual(
            _field_to_dict({"name": "dst", "type": "ipv4", "example": None}),
            {"name": "dst", "type": "ipv4"},
        )
