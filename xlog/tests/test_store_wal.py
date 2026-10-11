"""Several xlog server processes initialise the same brand-new database at once.

The PRAGMA that switches SQLite to WAL needs an exclusive lock and ignores the
busy timeout, so on a fresh file the processes that lose the race used to fail
with "database is locked", killing that worker's startup (seen as one of four
workers dying on a fresh install, then being respawned by the supervisor).
`store._enable_wal` retries while another process holds the lock.
"""

import multiprocessing
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("XLOG_DB_PATH", str(Path(tempfile.mkdtemp()) / "t.db"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import store  # noqa: E402


class _FakeConn:
    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = 0

    def execute(self, sql):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)


class TestEnableWal(unittest.TestCase):
    def setUp(self):
        self._sleep = store.time.sleep
        store.time.sleep = lambda s: None

    def tearDown(self):
        store.time.sleep = self._sleep

    def test_retries_while_another_process_holds_the_lock(self):
        conn = _FakeConn([sqlite3.OperationalError("database is locked")] * 3)
        store._enable_wal(conn)
        self.assertEqual(conn.calls, 4)

    def test_any_other_error_is_raised_immediately(self):
        conn = _FakeConn([sqlite3.OperationalError("disk I/O error")])
        with self.assertRaises(sqlite3.OperationalError):
            store._enable_wal(conn)
        self.assertEqual(conn.calls, 1)

    def test_gives_up_after_the_attempt_budget(self):
        conn = _FakeConn([sqlite3.OperationalError("database is locked")] * 1000)
        with self.assertRaises(sqlite3.OperationalError):
            store._enable_wal(conn)
        self.assertEqual(conn.calls, store._WAL_ATTEMPTS)


def _init_at_the_same_time(args):
    db_path, barrier = args
    os.environ["XLOG_DB_PATH"] = db_path
    from app import store as fresh
    fresh.DB_PATH = Path(db_path)
    barrier.wait()
    try:
        fresh.init_db()
        return None
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"


class TestConcurrentFirstInit(unittest.TestCase):
    def test_processes_racing_on_a_new_database_all_start(self):
        ctx = multiprocessing.get_context("spawn")
        failures = []
        for _ in range(4):
            db = str(Path(tempfile.mkdtemp()) / "race.db")
            with ctx.Manager() as manager:
                barrier = manager.Barrier(6)
                with ctx.Pool(6) as pool:
                    results = pool.map(_init_at_the_same_time, [(db, barrier)] * 6)
            failures += [r for r in results if r]
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
