import csv
import datetime as dt
import io
import json
import os
import sqlite3
import time
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


DB_PATH = Path(os.environ.get("XLOG_DB_PATH", "/data/xlog.db"))
_LOCK = threading.RLock()


def _now() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True)


def _loads(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


_WAL_ATTEMPTS = 100
_WAL_RETRY_SECONDS = 0.05


def _enable_wal(conn: Any) -> None:
    """Switch the database to WAL, tolerating other processes doing the same.

    xlog runs several server processes, and on a brand-new database file they
    all execute this PRAGMA at the same moment. The switch needs an exclusive
    lock and SQLite does not apply the busy timeout to it, so the losers fail
    at once with "database is locked", which kills that worker's startup.
    The mode is persistent: once any one process has switched, the rest only
    need to see it, so retrying for a moment always converges. The process-local
    _LOCK cannot help here, it does not span processes.
    """
    for attempt in range(_WAL_ATTEMPTS):
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == _WAL_ATTEMPTS - 1:
                raise
            time.sleep(_WAL_RETRY_SECONDS)


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    _enable_wal(conn)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with _LOCK, _connect() as conn:
        conn.executescript(
            """
            -- Streaming data workers live in a module-level dict with no
            -- persistence, so an xlog restart silently ends all log
            -- generation: list_workers returns empty and the platform looks
            -- idle rather than broken. Nothing surfaced it, and the analytics
            -- baselining clock it feeds only advances while data flows.
            --
            -- This table records enough to rebuild a worker on boot. Rows are
            -- deleted when a worker is stopped or reaped, so a non-empty table
            -- at startup means workers were running when the process died.
            CREATE TABLE IF NOT EXISTS worker_specs (
              worker_name TEXT PRIMARY KEY,
              spec_json TEXT NOT NULL,
              events_sent INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS simulation_runs (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              kind TEXT NOT NULL,
              status TEXT NOT NULL,
              destination TEXT,
              tags_json TEXT NOT NULL DEFAULT '[]',
              attack_json TEXT NOT NULL DEFAULT '{}',
              worker_ids_json TEXT NOT NULL DEFAULT '[]',
              caldera_operation_id TEXT,
              summary TEXT,
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS validation_results (
              id TEXT PRIMARY KEY,
              simulation_id TEXT NOT NULL,
              status TEXT NOT NULL,
              query TEXT,
              expected_json TEXT NOT NULL DEFAULT '{}',
              observed_json TEXT NOT NULL DEFAULT '{}',
              missed_json TEXT NOT NULL DEFAULT '[]',
              noisy_fields_json TEXT NOT NULL DEFAULT '[]',
              recommended_rules_json TEXT NOT NULL DEFAULT '[]',
              notes TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY(simulation_id) REFERENCES simulation_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS simulation_workers (
              id TEXT PRIMARY KEY,
              simulation_id TEXT NOT NULL,
              worker_id TEXT NOT NULL,
              status TEXT NOT NULL,
              destination TEXT,
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              FOREIGN KEY(simulation_id) REFERENCES simulation_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS scenario_packages (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              version TEXT NOT NULL DEFAULT '1.0',
              status TEXT NOT NULL DEFAULT 'draft',
              tags_json TEXT NOT NULL DEFAULT '[]',
              attack_json TEXT NOT NULL DEFAULT '{}',
              telemetry_json TEXT NOT NULL DEFAULT '{}',
              validation_json TEXT NOT NULL DEFAULT '{}',
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS run_artifacts (
              id TEXT PRIMARY KEY,
              simulation_id TEXT NOT NULL,
              artifact_type TEXT NOT NULL,
              name TEXT NOT NULL,
              content_type TEXT NOT NULL,
              content TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY(simulation_id) REFERENCES simulation_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS environment_profiles (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              stack_json TEXT NOT NULL DEFAULT '{}',
              default_destination TEXT,
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            -- Singleton row (id=1) holding the org's current technology
            -- stack. We keep this separate from `environment_profiles`
            -- (which is intended for multi-stack named-profile support
            -- as a future feature) so the read-path stays "fetch row 1"
            -- with no name resolution. The `TECHNOLOGY_STACK` env var
            -- remains the boot-time fallback when this table is empty;
            -- once an operator updates via mutation, the sqlite copy
            -- wins and survives restarts.
            CREATE TABLE IF NOT EXISTS technology_stack (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              stack_json TEXT NOT NULL DEFAULT '{}',
              updated_at TEXT NOT NULL,
              source TEXT NOT NULL DEFAULT 'manual'
            );
            """
        )


def _row_to_simulation(
    row: sqlite3.Row,
    validations: Optional[List[Dict[str, Any]]] = None,
    workers: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "status": row["status"],
        "destination": row["destination"],
        "tags": _loads(row["tags_json"], []),
        "attack": _loads(row["attack_json"], {}),
        "worker_ids": _loads(row["worker_ids_json"], []),
        "caldera_operation_id": row["caldera_operation_id"],
        "summary": row["summary"],
        "metadata": _loads(row["metadata_json"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "validations": validations or [],
        "workers": workers or [],
    }


def _row_to_validation(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "simulation_id": row["simulation_id"],
        "status": row["status"],
        "query": row["query"],
        "expected": _loads(row["expected_json"], {}),
        "observed": _loads(row["observed_json"], {}),
        "missed": _loads(row["missed_json"], []),
        "noisy_fields": _loads(row["noisy_fields_json"], []),
        "recommended_rules": _loads(row["recommended_rules_json"], []),
        "notes": row["notes"],
        "created_at": row["created_at"],
    }


def create_simulation_run(
    *,
    name: str,
    kind: str,
    status: str = "created",
    destination: Optional[str] = None,
    tags: Optional[List[str]] = None,
    attack: Optional[Dict[str, Any]] = None,
    worker_ids: Optional[List[str]] = None,
    caldera_operation_id: Optional[str] = None,
    summary: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    init_db()
    run_id = f"sim_{uuid.uuid4().hex[:12]}"
    now = _now()
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO simulation_runs
              (id, name, kind, status, destination, tags_json, attack_json, worker_ids_json,
               caldera_operation_id, summary, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                name,
                kind,
                status,
                destination,
                _json(tags or []),
                _json(attack or {}),
                _json(worker_ids or []),
                caldera_operation_id,
                summary,
                _json(metadata or {}),
                now,
                now,
            ),
        )
        for worker_id in worker_ids or []:
            conn.execute(
                """
                INSERT INTO simulation_workers
                  (id, simulation_id, worker_id, status, destination, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"worker_ref_{uuid.uuid4().hex[:12]}",
                    run_id,
                    worker_id,
                    status,
                    destination,
                    _json({}),
                    now,
                ),
            )
    return get_simulation_run(run_id) or {}


def update_simulation_status(run_id: str, status: str, metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    init_db()
    current = get_simulation_run(run_id)
    if not current:
        return None
    next_metadata = current.get("metadata", {})
    if metadata:
        next_metadata.update(metadata)
    with _LOCK, _connect() as conn:
        conn.execute(
            "UPDATE simulation_runs SET status = ?, metadata_json = ?, updated_at = ? WHERE id = ?",
            (status, _json(next_metadata), _now(), run_id),
        )
    return get_simulation_run(run_id)


def list_simulation_runs(limit: int = 50) -> List[Dict[str, Any]]:
    init_db()
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM simulation_runs ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 250)),),
        ).fetchall()
    return [_row_to_simulation(row) for row in rows]


def get_simulation_run(run_id: str) -> Optional[Dict[str, Any]]:
    init_db()
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM simulation_runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        validation_rows = conn.execute(
            "SELECT * FROM validation_results WHERE simulation_id = ? ORDER BY created_at DESC",
            (run_id,),
        ).fetchall()
        worker_rows = conn.execute(
            "SELECT * FROM simulation_workers WHERE simulation_id = ? ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
    return _row_to_simulation(
        row,
        [_row_to_validation(item) for item in validation_rows],
        [
            {
                "id": item["id"],
                "worker_id": item["worker_id"],
                "status": item["status"],
                "destination": item["destination"],
                "metadata": _loads(item["metadata_json"], {}),
                "created_at": item["created_at"],
            }
            for item in worker_rows
        ],
    )


def create_validation_result(
    *,
    simulation_id: str,
    status: str,
    query: Optional[str] = None,
    expected: Optional[Dict[str, Any]] = None,
    observed: Optional[Dict[str, Any]] = None,
    missed: Optional[List[str]] = None,
    noisy_fields: Optional[List[str]] = None,
    recommended_rules: Optional[List[str]] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    init_db()
    if not get_simulation_run(simulation_id):
        raise KeyError(f"Simulation run not found: {simulation_id}")
    validation_id = f"val_{uuid.uuid4().hex[:12]}"
    now = _now()
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO validation_results
              (id, simulation_id, status, query, expected_json, observed_json, missed_json,
               noisy_fields_json, recommended_rules_json, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                validation_id,
                simulation_id,
                status,
                query,
                _json(expected or {}),
                _json(observed or {}),
                _json(missed or []),
                _json(noisy_fields or []),
                _json(recommended_rules or []),
                notes,
                now,
            ),
        )
        conn.execute(
            "UPDATE simulation_runs SET status = ?, updated_at = ? WHERE id = ?",
            ("validated" if status.lower() in {"pass", "passed", "detected"} else "validation_review", now, simulation_id),
        )
    run = get_simulation_run(simulation_id)
    return run["validations"][0] if run and run.get("validations") else {}


def create_scenario_package(
    *,
    name: str,
    version: str = "1.0",
    status: str = "draft",
    tags: Optional[List[str]] = None,
    attack: Optional[Dict[str, Any]] = None,
    telemetry: Optional[Dict[str, Any]] = None,
    validation: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    init_db()
    package_id = f"pkg_{uuid.uuid4().hex[:12]}"
    now = _now()
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO scenario_packages
              (id, name, version, status, tags_json, attack_json, telemetry_json,
               validation_json, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                package_id,
                name,
                version,
                status,
                _json(tags or []),
                _json(attack or {}),
                _json(telemetry or {}),
                _json(validation or {}),
                _json(metadata or {}),
                now,
                now,
            ),
        )
    return get_scenario_package(package_id) or {}


def _row_to_package(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "version": row["version"],
        "status": row["status"],
        "tags": _loads(row["tags_json"], []),
        "attack": _loads(row["attack_json"], {}),
        "telemetry": _loads(row["telemetry_json"], {}),
        "validation": _loads(row["validation_json"], {}),
        "metadata": _loads(row["metadata_json"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_scenario_package(package_id: str) -> Optional[Dict[str, Any]]:
    init_db()
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM scenario_packages WHERE id = ?", (package_id,)).fetchone()
    return _row_to_package(row) if row else None


def list_scenario_packages(limit: int = 100) -> List[Dict[str, Any]]:
    init_db()
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM scenario_packages ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 250)),),
        ).fetchall()
    return [_row_to_package(row) for row in rows]


def coverage_report() -> Dict[str, Any]:
    runs = [
        get_simulation_run(item["id"]) or item
        for item in list_simulation_runs(limit=250)
    ]
    techniques: Dict[str, Dict[str, Any]] = {}
    missed: List[str] = []
    noisy_fields: List[str] = []
    recommended_rules: List[str] = []

    for run in runs:
        attack = run.get("attack") or {}
        technique = attack.get("technique_id") or attack.get("technique") or "unmapped"
        item = techniques.setdefault(
            technique,
            {"technique": technique, "runs": 0, "detected": 0, "missed": 0, "last_status": run["status"]},
        )
        item["runs"] += 1
        item["last_status"] = run["status"]
        for validation in run.get("validations", []):
            status = str(validation.get("status", "")).lower()
            if status in {"pass", "passed", "detected"}:
                item["detected"] += 1
            if status in {"fail", "failed", "missed"}:
                item["missed"] += 1
            missed.extend(validation.get("missed", []))
            noisy_fields.extend(validation.get("noisy_fields", []))
            recommended_rules.extend(validation.get("recommended_rules", []))

    return {
        "generated_at": _now(),
        "summary": {
            "simulation_runs": len(runs),
            "techniques": len(techniques),
            "detections": sum(item["detected"] for item in techniques.values()),
            "misses": sum(item["missed"] for item in techniques.values()),
        },
        "attack_coverage": sorted(techniques.values(), key=lambda item: item["technique"]),
        "missed_detections": sorted(set(missed)),
        "noisy_fields": sorted(set(noisy_fields)),
        "log_source_gaps": [],
        "recommended_rules": sorted(set(recommended_rules)),
    }


def export_simulation(run_id: str, artifact_format: str) -> str:
    run = get_simulation_run(run_id)
    if not run:
        raise KeyError(f"Simulation run not found: {run_id}")

    if artifact_format == "json":
        return json.dumps(run, indent=2, sort_keys=True)
    if artifact_format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=["id", "name", "kind", "status", "destination", "created_at"])
        writer.writeheader()
        writer.writerow({key: run.get(key) for key in writer.fieldnames})
        return buffer.getvalue()
    if artifact_format == "md":
        validations = run.get("validations", [])
        lines = [
            f"# {run['name']}",
            "",
            f"- ID: `{run['id']}`",
            f"- Kind: `{run['kind']}`",
            f"- Status: `{run['status']}`",
            f"- Destination: `{run.get('destination') or 'n/a'}`",
            f"- Created: `{run['created_at']}`",
            "",
            "## Attack Mapping",
            "```json",
            json.dumps(run.get("attack", {}), indent=2, sort_keys=True),
            "```",
            "",
            "## Validation Results",
        ]
        if validations:
            for validation in validations:
                lines.extend(
                    [
                        f"### {validation['id']}",
                        f"- Status: `{validation['status']}`",
                        f"- Notes: {validation.get('notes') or 'n/a'}",
                        "",
                    ]
                )
        else:
            lines.append("No validation results recorded yet.")
        return "\n".join(lines) + "\n"
    raise ValueError("Unsupported export format. Use json, csv, or md.")


# ─── Technology Stack ────────────────────────────────────────────────
#
# The "technology stack" is the org's catalog of vendor/product combos
# (Fortinet/FortiGate, CrowdStrike/Falcon, …) the agent biases simulation
# logs toward. Storage layers, by lookup priority:
#
#   1. SQLite singleton (this module) — operator-set via GraphQL mutation;
#      survives restarts.
#   2. TECHNOLOGY_STACK env var — boot-time fallback for legacy deploys
#      that haven't been migrated to the mutation path.
#   3. None — caller renders "configured: false" and the agent uses its
#      built-in default vendor catalog.


def _normalize_stack(stack: Dict[str, Any]) -> Dict[str, Any]:
    """Produce a canonical shape regardless of how loose the input was.

    The mutation accepts a Strawberry input that already enforces
    required fields, but env-var JSON or older callers might omit
    `vendors` or pass loose vendor entries. We normalize so reads
    are predictable downstream (e.g. consumers can rely on
    `vendors` being a list, even if empty).
    """
    if not isinstance(stack, dict):
        return {"stack_name": None, "log_destination": None, "vendors": []}
    vendors = stack.get("vendors") or []
    if not isinstance(vendors, list):
        vendors = []
    log_destination = stack.get("log_destination")
    if not isinstance(log_destination, dict):
        log_destination = None
    return {
        "stack_name": stack.get("stack_name"),
        "log_destination": log_destination,
        "vendors": vendors,
    }


def _env_fallback() -> Optional[Dict[str, Any]]:
    """Parse the TECHNOLOGY_STACK env var as JSON. Returns None if the
    env var is unset/empty/invalid (so the caller can decide between
    "configured: false" and another fallback path)."""
    raw = os.environ.get("TECHNOLOGY_STACK", "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return _normalize_stack(parsed)


def get_technology_stack() -> Dict[str, Any]:
    """Return the current technology stack with metadata.

    Lookup order: sqlite singleton → TECHNOLOGY_STACK env var → empty.
    The `source` field tells the caller where the data came from so
    the UI can show "operator-set" vs "boot-default" provenance.
    """
    init_db()
    with _LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT stack_json, updated_at, source FROM technology_stack WHERE id = 1"
        ).fetchone()
    if row is not None:
        stack = _normalize_stack(_loads(row["stack_json"], {}))
        return {
            **stack,
            "total_vendors": len(stack["vendors"]),
            "configured": bool(stack["stack_name"] or stack["vendors"]),
            "updated_at": row["updated_at"],
            "source": row["source"] or "manual",
        }
    env_stack = _env_fallback()
    if env_stack is not None:
        return {
            **env_stack,
            "total_vendors": len(env_stack["vendors"]),
            "configured": bool(env_stack["stack_name"] or env_stack["vendors"]),
            "updated_at": None,
            "source": "env",
        }
    return {
        "stack_name": None,
        "log_destination": None,
        "vendors": [],
        "total_vendors": 0,
        "configured": False,
        "updated_at": None,
        "source": "default",
    }


def update_technology_stack(stack: Dict[str, Any]) -> Dict[str, Any]:
    """Upsert the singleton row with the given stack and return the
    new state. The input is normalized (bad shapes get coerced to
    empty rather than raising) — strict validation is the resolver's
    job since GraphQL has its own input types."""
    init_db()
    normalized = _normalize_stack(stack)
    now = _now()
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO technology_stack (id, stack_json, updated_at, source)
            VALUES (1, ?, ?, 'manual')
            ON CONFLICT(id) DO UPDATE SET
              stack_json = excluded.stack_json,
              updated_at = excluded.updated_at,
              source = 'manual'
            """,
            (_json(normalized), now),
        )
    return get_technology_stack()


def clear_technology_stack() -> Dict[str, Any]:
    """Delete the singleton row. After this, get_technology_stack() falls
    back to the env var (or default). Used by tests and by the
    rare 'reset to factory' flow."""
    init_db()
    with _LOCK, _connect() as conn:
        conn.execute("DELETE FROM technology_stack WHERE id = 1")
    return get_technology_stack()


# ── worker-spec persistence ──────────────────────────────────────────
#
# Enough to reconstruct a streaming worker after a restart. Deliberately
# stores the CREATE REQUEST rather than the live sender object: the request
# is small, JSON-safe, and already validated, whereas a sender carries a
# socket and a thread that cannot be serialized.


def save_worker_spec(worker_name: str, spec: Dict[str, Any]) -> None:
    """Record a worker so it can be rebuilt after a restart."""
    now = _now()
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO worker_specs (worker_name, spec_json, events_sent,
                                      created_at, updated_at)
            VALUES (?, ?, 0, ?, ?)
            ON CONFLICT(worker_name) DO UPDATE SET
              spec_json = excluded.spec_json,
              updated_at = excluded.updated_at
            """,
            (worker_name, _json(spec), now, now),
        )


def update_worker_progress(worker_name: str, events_sent: int) -> None:
    """Checkpoint how much of a bounded worker's budget is already spent.

    Without this a restart would restore a burst worker with a FULL budget,
    so a 50,000-event burst could be replayed in its entirety on every
    restart — turning a crash loop into an amplifier.
    """
    with _LOCK, _connect() as conn:
        conn.execute(
            "UPDATE worker_specs SET events_sent = ?, updated_at = ? "
            "WHERE worker_name = ?",
            (int(events_sent), _now(), worker_name),
        )


def delete_worker_spec(worker_name: str) -> None:
    with _LOCK, _connect() as conn:
        conn.execute(
            "DELETE FROM worker_specs WHERE worker_name = ?", (worker_name,)
        )


def list_worker_specs() -> List[Dict[str, Any]]:
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT worker_name, spec_json, events_sent, created_at, updated_at "
            "FROM worker_specs ORDER BY created_at"
        ).fetchall()
    return [
        {
            "worker_name": r["worker_name"],
            "spec": _loads(r["spec_json"], {}),
            "events_sent": r["events_sent"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def clear_worker_specs() -> int:
    with _LOCK, _connect() as conn:
        cur = conn.execute("DELETE FROM worker_specs")
        return cur.rowcount or 0
