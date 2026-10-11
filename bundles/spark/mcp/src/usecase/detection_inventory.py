"""SqliteDetectionInventory — operational record of every XSIAM
detection (correlation rule) that has fired against this deploy.

Why "fires-derived" rather than "ruleset-derived":

  XSIAM's PAPI doesn't expose a typed "list correlation rules"
  endpoint that phantom uses today (`/issue/search/` is the only
  public detection-side ingress in the connector). Building the
  inventory from the issues stream has a useful property the
  ruleset path lacks: it's grounded in OPERATIONAL reality. Rules
  that exist but never fire don't appear; rules that fire are
  tracked even if they're not in the operator's "official"
  ruleset YAML. This matches what SOC operators care about —
  "what detections are ALIVE", not "what's defined".

  Dark detections — rules that are defined but have never fired
  — are a separate problem. A future `manual` source value can
  let operators declare them, surfaced in `coverage_gaps` as
  "configured but silent". Schema is forward-compatible.

# Schema

  detection_fires(
    issue_id        TEXT PRIMARY KEY,    -- XSIAM issue UUID
    rule_id         TEXT NOT NULL,        -- correlation_rule_id (group key)
    rule_name       TEXT,                 -- human-readable
    severity        TEXT,                 -- low | medium | high | critical
    detection_method TEXT,                -- correlation | analytics | xdr | bioc
    technique_ids   TEXT NOT NULL,        -- JSON array of MITRE T-codes
    fired_at        TEXT NOT NULL,        -- ISO8601 from XSIAM _insert_time
    fetched_at      TEXT NOT NULL,        -- when phantom ingested it
    raw_json        TEXT NOT NULL         -- original issue blob (debug + future fields)
  );
  CREATE INDEX idx_rule_id   ON detection_fires(rule_id);
  CREATE INDEX idx_fired_at  ON detection_fires(fired_at);
  CREATE INDEX idx_severity  ON detection_fires(severity);

The PRIMARY KEY on issue_id makes the sync idempotent: replaying the
same XSIAM `/issue/search/` window upserts no new rows.

# Read-side aggregations

`list_rules()` and `rule_summary(rule_id)` aggregate over the fires
table to answer the questions the agent + UI need:
  - Which rules have fired in the last 24h / 7d / 30d?
  - When did rule X last fire?
  - What MITRE techniques does rule X cover (union over all fires)?

We don't materialize a `detection_rules` table because the answers
are cheap to compute against indexed fires (~milliseconds at typical
SOC-deploy scale: thousands of fires, hundreds of rules).

# Audit

`detections_synced` and `coverage_gap_observed` are declared in
manifest.audit.events and emitted from the sync + gap-find paths.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger("Phantom MCP")

DEFAULT_DATA_ROOT = Path("/app/data")


@dataclass(frozen=True)
class DetectionFire:
    """One row materialized from detection_fires."""

    issue_id: str
    rule_id: str
    rule_name: str | None
    severity: str | None
    detection_method: str | None
    technique_ids: list[str]
    fired_at: str
    fetched_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "severity": self.severity,
            "detection_method": self.detection_method,
            "technique_ids": list(self.technique_ids),
            "fired_at": self.fired_at,
            "fetched_at": self.fetched_at,
        }


@dataclass(frozen=True)
class RuleSummary:
    """Per-rule aggregation across all its fires."""

    rule_id: str
    rule_name: str | None
    severity: str | None
    detection_method: str | None
    technique_ids: list[str]
    fires_total: int
    fires_24h: int
    fires_7d: int
    fires_30d: int
    first_fire_at: str
    last_fire_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "severity": self.severity,
            "detection_method": self.detection_method,
            "technique_ids": list(self.technique_ids),
            "fires_total": self.fires_total,
            "fires_24h": self.fires_24h,
            "fires_7d": self.fires_7d,
            "fires_30d": self.fires_30d,
            "first_fire_at": self.first_fire_at,
            "last_fire_at": self.last_fire_at,
        }


class SqliteDetectionInventory:
    """Sqlite-backed detection-fire log at <data_root>/detections.db."""

    def __init__(self, data_root: Path | None = None) -> None:
        self._data_root = (data_root or self._resolve_data_root()).resolve()
        self._data_root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_root / "detections.db"
        self._lock = threading.Lock()
        self._init_schema()
        logger.info("SqliteDetectionInventory at %s", self._db_path)

    @staticmethod
    def _resolve_data_root() -> Path:
        raw = os.getenv("DATA_ROOT", str(DEFAULT_DATA_ROOT))
        return Path(raw)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._db_path, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    def _init_schema(self) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS detection_fires (
                    issue_id        TEXT PRIMARY KEY,
                    rule_id         TEXT NOT NULL,
                    rule_name       TEXT,
                    severity        TEXT,
                    detection_method TEXT,
                    technique_ids   TEXT NOT NULL,
                    fired_at        TEXT NOT NULL,
                    fetched_at      TEXT NOT NULL,
                    raw_json        TEXT NOT NULL
                )
                """
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_rule_id "
                "ON detection_fires(rule_id)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_fired_at "
                "ON detection_fires(fired_at)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_severity "
                "ON detection_fires(severity)"
            )

    @staticmethod
    def _now_iso() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # ─── Write path (used by detections_sync) ────────────────────

    def upsert_fires(self, issues: Iterable[dict[str, Any]]) -> dict[str, int]:
        """Upsert raw issue dicts from XSIAM's /issue/search/ response.

        The XSIAM payload shape varies by tenant; we extract the
        defensive minimum: issue_id, correlation_rule_id, rule_name,
        severity, detection_method, _insert_time, mitre_technique_id_and_name.
        Issues missing the rule_id (e.g. raw alerts not mapped to a
        correlation rule) are skipped — they're not "detections" in
        the operator's sense.

        Returns {inserted, skipped, total}.
        """
        inserted = 0
        skipped = 0
        total = 0
        now = self._now_iso()
        rows_to_write: list[tuple] = []
        for issue in issues:
            total += 1
            if not isinstance(issue, dict):
                skipped += 1
                continue
            issue_id = (
                issue.get("issue_id")
                or issue.get("id")
                or issue.get("_id")
            )
            rule_id = (
                issue.get("correlation_rule_id")
                or issue.get("rule_id")
                or issue.get("alert_id")
            )
            if not issue_id or not rule_id:
                skipped += 1
                continue
            rule_name = (
                issue.get("rule_name")
                or issue.get("alert_name")
                or issue.get("name")
            )
            severity = issue.get("severity") or issue.get("alert_severity")
            method = (
                issue.get("detection_method")
                or issue.get("source")
                or issue.get("detector")
            )
            techs = _extract_technique_ids(issue)
            fired_at = (
                issue.get("_insert_time")
                or issue.get("alert_time")
                or issue.get("event_time")
                or now
            )
            rows_to_write.append((
                str(issue_id),
                str(rule_id),
                rule_name,
                str(severity).lower() if severity else None,
                str(method) if method else None,
                json.dumps(techs),
                str(fired_at),
                now,
                json.dumps(issue, default=str),
            ))

        if rows_to_write:
            with self._lock, self._conn() as c:
                # ON CONFLICT keeps the first-seen row; we don't
                # overwrite because XSIAM's issue records are
                # immutable once issued (status updates create new
                # events, not amendments).
                #
                # Counting inserts: `SELECT changes()` returns only
                # the row-count from the most recent statement, so
                # after an executemany of N rows it reflects only the
                # final row's effect (always 0 or 1). The connection's
                # `total_changes` attribute IS cumulative for the
                # lifetime of the connection — diff before/after to
                # get the batch count.
                before = c.total_changes
                c.executemany(
                    "INSERT OR IGNORE INTO detection_fires "
                    "(issue_id, rule_id, rule_name, severity, "
                    " detection_method, technique_ids, fired_at, "
                    " fetched_at, raw_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    rows_to_write,
                )
                inserted = c.total_changes - before

        from usecase.audit_log import (  # late-import: audit module
            ACTION_DETECTIONS_SYNCED,    # may not be defined when
            record_event,                 # tests run in isolation.
        )
        try:
            record_event(
                ACTION_DETECTIONS_SYNCED,
                target="detection_inventory",
                status="success",
                metadata={
                    "total": total,
                    "inserted": inserted,
                    "skipped": skipped,
                },
            )
        except Exception:  # noqa: BLE001
            # Audit failures must not block the sync — the inserts
            # are already committed at this point.
            pass

        return {
            "inserted": int(inserted),
            "skipped": skipped,
            "total": total,
        }

    # ─── Read path ───────────────────────────────────────────────

    def list_fires(
        self,
        *,
        rule_id: str | None = None,
        since: str | None = None,
        limit: int | None = None,
    ) -> list[DetectionFire]:
        """Recent fires, newest first. Optional filter by rule + min time.

        No default limit and no hard cap. Pagination is opt-in.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if rule_id:
            clauses.append("rule_id = ?")
            params.append(rule_id)
        if since:
            clauses.append("fired_at >= ?")
            params.append(since)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        eff_limit = -1 if (limit is None or int(limit) <= 0) else int(limit)
        params.append(eff_limit)
        with self._lock, self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM detection_fires {where} "
                "ORDER BY fired_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [_row_to_fire(r) for r in rows]

    def list_rules(
        self,
        *,
        severity: str | None = None,
        technique: str | None = None,
        limit: int | None = None,
    ) -> list[RuleSummary]:
        """Aggregate over fires to return one row per rule with
        fire counts in standard windows + technique union."""
        # Per-rule aggregation. We pull all matching fires and
        # roll up in Python — keeps SQL simple and lets us union
        # technique_ids across rows. At SOC scale this is fine.
        clauses: list[str] = []
        params: list[Any] = []
        if severity:
            clauses.append("severity = ?")
            params.append(severity.lower())
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock, self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM detection_fires {where} "
                "ORDER BY fired_at DESC",
                params,
            ).fetchall()

        now_epoch = time.time()
        cutoff_24h = now_epoch - 24 * 3600
        cutoff_7d = now_epoch - 7 * 24 * 3600
        cutoff_30d = now_epoch - 30 * 24 * 3600

        per_rule: dict[str, dict[str, Any]] = {}
        for r in rows:
            rid = r["rule_id"]
            ts_epoch = _parse_iso_to_epoch(r["fired_at"])
            techs = json.loads(r["technique_ids"] or "[]")
            cur = per_rule.get(rid)
            if cur is None:
                cur = {
                    "rule_id": rid,
                    "rule_name": r["rule_name"],
                    "severity": r["severity"],
                    "detection_method": r["detection_method"],
                    "technique_ids": set(techs),
                    "fires_total": 0,
                    "fires_24h": 0,
                    "fires_7d": 0,
                    "fires_30d": 0,
                    "first_fire_at": r["fired_at"],
                    "last_fire_at": r["fired_at"],
                }
                per_rule[rid] = cur
            cur["technique_ids"].update(techs)
            cur["fires_total"] += 1
            if ts_epoch >= cutoff_24h:
                cur["fires_24h"] += 1
            if ts_epoch >= cutoff_7d:
                cur["fires_7d"] += 1
            if ts_epoch >= cutoff_30d:
                cur["fires_30d"] += 1
            # Rows are ORDER BY fired_at DESC, so the FIRST row we
            # see for a rule has the latest fire. Subsequent rows
            # update first_fire_at as we walk back in time.
            cur["first_fire_at"] = r["fired_at"]

        out: list[RuleSummary] = []
        for cur in per_rule.values():
            techs = sorted(cur["technique_ids"])
            if technique and technique not in techs:
                continue
            out.append(RuleSummary(
                rule_id=cur["rule_id"],
                rule_name=cur["rule_name"],
                severity=cur["severity"],
                detection_method=cur["detection_method"],
                technique_ids=techs,
                fires_total=cur["fires_total"],
                fires_24h=cur["fires_24h"],
                fires_7d=cur["fires_7d"],
                fires_30d=cur["fires_30d"],
                first_fire_at=cur["first_fire_at"],
                last_fire_at=cur["last_fire_at"],
            ))
        # Most-recently-fired first — matches what dashboards expect.
        out.sort(key=lambda s: s.last_fire_at, reverse=True)
        # No default cap; pagination is opt-in.
        if limit is None or int(limit) <= 0:
            return out
        return out[: int(limit)]

    def rule_summary(self, rule_id: str) -> RuleSummary | None:
        rows = self.list_rules(limit=500)
        for r in rows:
            if r.rule_id == rule_id:
                return r
        return None

    def technique_coverage(self) -> dict[str, dict[str, Any]]:
        """For every technique seen across all fires, return:
            {T-code: {rules_count, fires_24h, fires_7d, fires_30d, last_fire_at}}

        Used by `coverage_gaps` (silent techniques) and the closed-
        loop drift snapshot.
        """
        now_epoch = time.time()
        cutoff_24h = now_epoch - 24 * 3600
        cutoff_7d = now_epoch - 7 * 24 * 3600
        cutoff_30d = now_epoch - 30 * 24 * 3600

        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT rule_id, technique_ids, fired_at "
                "FROM detection_fires"
            ).fetchall()
        per_tech: dict[str, dict[str, Any]] = {}
        for r in rows:
            techs = json.loads(r["technique_ids"] or "[]")
            ts_epoch = _parse_iso_to_epoch(r["fired_at"])
            for t in techs:
                cur = per_tech.get(t)
                if cur is None:
                    cur = {
                        "technique_id": t,
                        "rules": set(),
                        "fires_24h": 0,
                        "fires_7d": 0,
                        "fires_30d": 0,
                        "last_fire_at": r["fired_at"],
                    }
                    per_tech[t] = cur
                cur["rules"].add(r["rule_id"])
                if ts_epoch >= cutoff_24h:
                    cur["fires_24h"] += 1
                if ts_epoch >= cutoff_7d:
                    cur["fires_7d"] += 1
                if ts_epoch >= cutoff_30d:
                    cur["fires_30d"] += 1
                if r["fired_at"] > cur["last_fire_at"]:
                    cur["last_fire_at"] = r["fired_at"]
        return {
            t: {
                "technique_id": t,
                "rules_count": len(d["rules"]),
                "fires_24h": d["fires_24h"],
                "fires_7d": d["fires_7d"],
                "fires_30d": d["fires_30d"],
                "last_fire_at": d["last_fire_at"],
            }
            for t, d in per_tech.items()
        }


# ─── Helpers ─────────────────────────────────────────────────────


def _row_to_fire(row: sqlite3.Row) -> DetectionFire:
    return DetectionFire(
        issue_id=row["issue_id"],
        rule_id=row["rule_id"],
        rule_name=row["rule_name"],
        severity=row["severity"],
        detection_method=row["detection_method"],
        technique_ids=json.loads(row["technique_ids"] or "[]"),
        fired_at=row["fired_at"],
        fetched_at=row["fetched_at"],
    )


def _parse_iso_to_epoch(s: str) -> float:
    """Best-effort ISO8601 → epoch. XSIAM uses millisecond timestamps
    in some endpoints, ISO strings in others; handle both."""
    if not s:
        return 0.0
    if s.isdigit() and len(s) >= 10:
        # Epoch seconds (10 digits) or millis (13).
        n = int(s)
        return n / 1000.0 if len(s) >= 13 else float(n)
    # Try the common ISO formats.
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return time.mktime(time.strptime(s.split("+")[0], fmt))
        except ValueError:
            continue
    return 0.0


# Common keys XSIAM uses to attach MITRE ATT&CK metadata. The PAPI
# response shape varies; we try the major variants and return a flat
# list of T-codes (e.g. "T1078", "T1059.001").
_MITRE_KEYS = (
    "mitre_technique_id_and_name",
    "mitre_techniques",
    "mitre_technique_ids",
    "mitre_technique_id",
    "techniques",
)


def _extract_technique_ids(issue: dict[str, Any]) -> list[str]:
    """Pull MITRE T-codes from an issue. Robust to mixed shapes:
    list-of-strings, list-of-objects with `id` field, "T1078, T1059"
    comma-strings."""
    seen: list[str] = []

    def _push(s: str) -> None:
        # Match T-codes including sub-techniques: T1078, T1059.001
        import re
        for m in re.findall(r"T\d{4}(?:\.\d{3})?", s):
            if m not in seen:
                seen.append(m)

    for k in _MITRE_KEYS:
        v = issue.get(k)
        if v is None:
            continue
        if isinstance(v, str):
            _push(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    _push(item)
                elif isinstance(item, dict):
                    _push(str(item.get("id") or item.get("name") or ""))
                else:
                    _push(str(item))
        elif isinstance(v, dict):
            _push(str(v.get("id") or v.get("name") or ""))
    return seen


# ─────────────────────────────────────────────────────────────────
# Module-level singleton accessor — wired by main.py.
# ─────────────────────────────────────────────────────────────────


_inventory: SqliteDetectionInventory | None = None


def set_detection_inventory(inv: SqliteDetectionInventory | None) -> None:
    global _inventory
    _inventory = inv


def detection_inventory() -> SqliteDetectionInventory | None:
    return _inventory
