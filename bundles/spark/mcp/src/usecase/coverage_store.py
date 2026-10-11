"""SqliteCoverageStore — point-in-time snapshots of the detection
inventory, used for drift detection and operator-facing dashboards.

# Design

  A snapshot is the per-rule + per-technique aggregation of the
  inventory at a moment in time. Stored as a single JSON blob
  per row — `body_json` carries the full state. We don't shred
  it across normalized tables because:

  - **Diffs are JSON-against-JSON**: the diff renderer compares two
    snapshots' JSON, doesn't need indexed access to individual fields.
  - **Schema-free**: future inventory shape changes (new fields,
    new aggregation windows) flow into snapshots without migrations.
  - **Cheap**: a snapshot for a deploy with hundreds of rules is
    well under 100KB of JSON. 365 days of daily snapshots = ~36MB.
    Trivially storable.

  Trade-off: ad-hoc SQL queries like "rules silent in the last
  N snapshots" need Python iteration over rows. Acceptable —
  drift detection is interactive (operator-driven), not at scale.

# Schema

  coverage_snapshots(
    id          TEXT PRIMARY KEY,    -- uuid4
    taken_at    TEXT NOT NULL,       -- ISO8601 UTC
    label       TEXT,                 -- optional operator note
    body_json   TEXT NOT NULL,       -- the snapshot payload
    actor       TEXT                  -- who triggered it
  );
  CREATE INDEX idx_taken_at ON coverage_snapshots(taken_at);

# Snapshot body shape

  {
    "rules": {
      "<rule_id>": {
        "rule_id": ..., "rule_name": ..., "severity": ...,
        "fires_total": int, "fires_24h": int, "fires_7d": int,
        "fires_30d": int, "first_fire_at": ISO, "last_fire_at": ISO,
        "technique_ids": [T-codes...]
      },
      ...
    },
    "techniques": {
      "<T-code>": {
        "technique_id": ..., "rules_count": int,
        "fires_24h": int, "fires_7d": int, "fires_30d": int,
        "last_fire_at": ISO
      },
      ...
    },
    "totals": {
      "rule_count": int, "technique_count": int,
      "fires_24h": int, "fires_7d": int, "fires_30d": int
    }
  }
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("Phantom MCP")

DEFAULT_DATA_ROOT = Path("/app/data")


@dataclass(frozen=True)
class CoverageSnapshot:
    """One snapshot row, materialized."""

    id: str
    taken_at: str
    label: str | None
    actor: str | None
    body: dict[str, Any]

    def to_dict(self, *, include_body: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "taken_at": self.taken_at,
            "label": self.label,
            "actor": self.actor,
        }
        if include_body:
            out["body"] = self.body
        # Even when body is omitted, expose the headline totals so
        # list views can render summary chips without a second fetch.
        totals = self.body.get("totals") if isinstance(self.body, dict) else None
        if isinstance(totals, dict):
            out["totals"] = totals
        return out


class SqliteCoverageStore:
    """Sqlite-backed coverage-snapshot store at <data_root>/coverage.db."""

    def __init__(self, data_root: Path | None = None) -> None:
        self._data_root = (data_root or self._resolve_data_root()).resolve()
        self._data_root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_root / "coverage.db"
        self._lock = threading.Lock()
        self._init_schema()
        logger.info("SqliteCoverageStore at %s", self._db_path)

    @staticmethod
    def _resolve_data_root() -> Path:
        raw = os.getenv("DATA_ROOT", str(DEFAULT_DATA_ROOT))
        return Path(raw)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(
            self._db_path, isolation_level=None, check_same_thread=False
        )
        c.row_factory = sqlite3.Row
        return c

    def _init_schema(self) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS coverage_snapshots (
                    id          TEXT PRIMARY KEY,
                    taken_at    TEXT NOT NULL,
                    label       TEXT,
                    body_json   TEXT NOT NULL,
                    actor       TEXT
                )
                """
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_taken_at "
                "ON coverage_snapshots(taken_at)"
            )

    @staticmethod
    def _now_iso() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # ─── Take ────────────────────────────────────────────────────

    def take(
        self,
        body: dict[str, Any],
        *,
        label: str | None = None,
        actor: str | None = None,
    ) -> CoverageSnapshot:
        """Persist a new snapshot. The caller (the coverage_snapshot_take
        tool) builds the body from the live inventory aggregations.

        Args:
            body: snapshot payload — see module docstring for shape.
            label: optional operator-supplied note ("after T1078 sim",
                "post-rule-update", etc).
            actor: who took the snapshot ("agent", "user:operator",
                "scheduler:continuous-coverage-cycle").
        """
        if not isinstance(body, dict):
            raise TypeError("snapshot body must be a dict")
        sid = str(uuid.uuid4())
        now = self._now_iso()
        body_json = json.dumps(body, ensure_ascii=False, default=str, sort_keys=True)
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO coverage_snapshots "
                "(id, taken_at, label, body_json, actor) "
                "VALUES (?, ?, ?, ?, ?)",
                (sid, now, label, body_json, actor),
            )

        try:
            from usecase.audit_log import (
                ACTION_COVERAGE_SNAPSHOT_TAKEN,
                record_event,
            )
            totals = body.get("totals", {}) if isinstance(body, dict) else {}
            record_event(
                ACTION_COVERAGE_SNAPSHOT_TAKEN,
                target=f"coverage_snapshot:{sid}",
                status="success",
                actor=actor,
                metadata={
                    "snapshot_id": sid,
                    "label": label,
                    "rule_count": totals.get("rule_count"),
                    "technique_count": totals.get("technique_count"),
                },
            )
        except Exception:  # noqa: BLE001
            # Audit failure must not block the snapshot insert.
            pass

        return CoverageSnapshot(
            id=sid, taken_at=now, label=label, actor=actor, body=body,
        )

    # ─── Read ────────────────────────────────────────────────────

    def get(self, snapshot_id: str) -> CoverageSnapshot | None:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT * FROM coverage_snapshots WHERE id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_snapshot(row)

    def list_recent(
        self, *, limit: int = 50, label: str | None = None,
    ) -> list[CoverageSnapshot]:
        clauses = ""
        params: list[Any] = []
        if label:
            clauses = "WHERE label = ?"
            params.append(label)
        params.append(max(1, min(int(limit), 500)))
        with self._lock, self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM coverage_snapshots {clauses} "
                "ORDER BY taken_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [_row_to_snapshot(r) for r in rows]

    def latest(self, *, label: str | None = None) -> CoverageSnapshot | None:
        rows = self.list_recent(limit=1, label=label)
        return rows[0] if rows else None


def _row_to_snapshot(row: sqlite3.Row) -> CoverageSnapshot:
    return CoverageSnapshot(
        id=row["id"],
        taken_at=row["taken_at"],
        label=row["label"],
        actor=row["actor"],
        body=json.loads(row["body_json"]) if row["body_json"] else {},
    )


# ─────────────────────────────────────────────────────────────────
# Snapshot diff — pure function on two body dicts.
# ─────────────────────────────────────────────────────────────────


def diff_snapshots(
    older: dict[str, Any], newer: dict[str, Any],
) -> dict[str, Any]:
    """Compute a drift report between two snapshot bodies.

    Drift signals (per rule):
      - "went_silent": fired in older.fires_24h but not in newer.fires_24h
      - "new_active": absent or 0 fires in older, but firing in newer
      - "fire_rate_drop": newer.fires_24h < 0.5 × older.fires_24h
        AND older.fires_24h >= 4 (avoid noisy small-N comparisons)

    Drift signals (per technique):
      - "went_uncovered": techniques with rules_count > 0 in older
        but rules_count == 0 in newer
      - "newly_covered":  techniques absent in older but present in newer

    Returns a structured report:
      {
        "rules": {
          "went_silent":     [{rule_id, rule_name, prev_fires_24h, ...}],
          "new_active":      [...],
          "fire_rate_drop":  [...]
        },
        "techniques": {
          "went_uncovered":  [{technique_id, prev_rules_count}],
          "newly_covered":   [{technique_id, rules_count, last_fire_at}]
        },
        "summary": {
          "total_signals": int,
          "older_at": ISO, "newer_at": ISO,  // populated by caller
        }
      }
    """
    older_rules = (older.get("rules") or {}) if isinstance(older, dict) else {}
    newer_rules = (newer.get("rules") or {}) if isinstance(newer, dict) else {}

    went_silent: list[dict[str, Any]] = []
    new_active: list[dict[str, Any]] = []
    fire_rate_drop: list[dict[str, Any]] = []

    for rule_id, old_r in older_rules.items():
        new_r = newer_rules.get(rule_id)
        old_24h = int(old_r.get("fires_24h") or 0)
        if new_r is None:
            # Rule existed in older snapshot, missing in newer — could
            # mean the inventory dropped it (TTL) or the rule was
            # removed entirely. Surface as "went silent" with a note.
            if old_24h > 0:
                went_silent.append({
                    "rule_id": rule_id,
                    "rule_name": old_r.get("rule_name"),
                    "prev_fires_24h": old_24h,
                    "reason": "absent_from_newer_snapshot",
                })
            continue
        new_24h = int(new_r.get("fires_24h") or 0)
        if old_24h > 0 and new_24h == 0:
            went_silent.append({
                "rule_id": rule_id,
                "rule_name": old_r.get("rule_name"),
                "prev_fires_24h": old_24h,
                "now_fires_24h": new_24h,
                "reason": "stopped_firing",
            })
        elif old_24h >= 4 and new_24h * 2 < old_24h:
            fire_rate_drop.append({
                "rule_id": rule_id,
                "rule_name": old_r.get("rule_name"),
                "prev_fires_24h": old_24h,
                "now_fires_24h": new_24h,
                "drop_ratio": round(1 - (new_24h / old_24h), 2),
            })

    for rule_id, new_r in newer_rules.items():
        old_r = older_rules.get(rule_id)
        new_24h = int(new_r.get("fires_24h") or 0)
        if old_r is None and new_24h > 0:
            new_active.append({
                "rule_id": rule_id,
                "rule_name": new_r.get("rule_name"),
                "now_fires_24h": new_24h,
            })

    older_techs = (older.get("techniques") or {}) if isinstance(older, dict) else {}
    newer_techs = (newer.get("techniques") or {}) if isinstance(newer, dict) else {}
    went_uncovered: list[dict[str, Any]] = []
    newly_covered: list[dict[str, Any]] = []

    for t, old_t in older_techs.items():
        new_t = newer_techs.get(t)
        if new_t is None or int(new_t.get("rules_count") or 0) == 0:
            went_uncovered.append({
                "technique_id": t,
                "prev_rules_count": int(old_t.get("rules_count") or 0),
            })

    for t, new_t in newer_techs.items():
        if t not in older_techs:
            newly_covered.append({
                "technique_id": t,
                "rules_count": int(new_t.get("rules_count") or 0),
                "last_fire_at": new_t.get("last_fire_at"),
            })

    total_signals = (
        len(went_silent) + len(new_active) + len(fire_rate_drop)
        + len(went_uncovered) + len(newly_covered)
    )

    return {
        "rules": {
            "went_silent": went_silent,
            "new_active": new_active,
            "fire_rate_drop": fire_rate_drop,
        },
        "techniques": {
            "went_uncovered": went_uncovered,
            "newly_covered": newly_covered,
        },
        "summary": {
            "total_signals": total_signals,
            "rules_silent_count": len(went_silent),
            "rules_new_count": len(new_active),
            "rules_dropping_count": len(fire_rate_drop),
            "techniques_uncovered_count": len(went_uncovered),
            "techniques_new_count": len(newly_covered),
        },
    }


# ─────────────────────────────────────────────────────────────────
# Module-level singleton accessor — wired by main.py.
# ─────────────────────────────────────────────────────────────────


_store: SqliteCoverageStore | None = None


def set_coverage_store(s: SqliteCoverageStore | None) -> None:
    global _store
    _store = s


def coverage_store() -> SqliteCoverageStore | None:
    return _store
