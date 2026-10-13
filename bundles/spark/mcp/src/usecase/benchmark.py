"""Benchmark harness scaffolding.

Mirrors Octagon's `Manifest + BenchCase + scorer + runner` pattern,
scaled down:

  - Manifest YAML format + Pydantic parsing
  - 5-axis scorer (correctness, tool-call accuracy, cost, wall p50/p95,
    regression)
  - Runner that dispatches each case via the existing chat-route HTTP
    endpoint (same wire the scheduler uses for job-driven runs)
  - MCP tool `bench_run` so operators can fire a benchmark from chat
    (and store the result in benchmark_runs.db)
  - Sample corpus at `bench_cases/phantom-soc-v1/` (3 cases) to seed
    the format

Not yet implemented:
  - `/observability/bench` page + compare view + drill-down
  - CLI binary `phantom bench run` / `phantom bench compare`
  - Larger corpus (10-20 cases) + val/test split via salted hash
  - Bench scheduling job (weekly auto-run)
  - Regression flag integration with release-gating

This module provides the storage + scoring + MCP-tool surface. The
operator runs benchmarks by asking the agent ("run the
phantom-soc-v1 bench manifest, default routing preset") and reads
the result JSON from the audit log. The UI lands when the operator
validates the scoring shape is sensible.

# Manifest YAML format

    manifest:
      id: phantom-soc-v1
      version: "1.0"
      description: "Sample SOC-scenario benchmark"
      cases:
        - id: generate-iocs
          prompt: "Generate 5 IOCs for a phishing scenario"
          expected_output_match: "iocs"          # substring / regex
          expected_tool_calls:                    # ordered tool names
            - phantom_create_data_worker
          max_wall_seconds: 60.0
        - id: detect-bruteforce
          prompt: "Detect a brute-force attack pattern in the xlog stream"
          expected_output_match: "brute-force"
          expected_tool_calls:
            - xlog_query
          max_wall_seconds: 120.0
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("Phantom MCP")

DEFAULT_DATA_ROOT = Path("/app/data")


# ─── Manifest parsing ────────────────────────────────────────────────


class BenchCase(BaseModel):
    """One case in a manifest. Mirrors Octagon's BenchCase but scaled
    down to Phantom's chat-route semantics — we dispatch a prompt and
    score the resulting tool calls + output text, rather than running
    a phased pipeline."""

    id: str = Field(..., description="Unique within the manifest.")
    prompt: str
    expected_output_match: str | None = Field(
        default=None,
        description=(
            "Substring or regex the final response should contain to count "
            "as correct. None = correctness not scored on this case."
        ),
    )
    expected_tool_calls: list[str] = Field(
        default_factory=list,
        description=(
            "Tool names the agent should call. Order-agnostic match "
            "(Jaccard similarity). Order-sensitive scoring is not "
            "implemented."
        ),
    )
    max_wall_seconds: float = Field(
        default=120.0,
        description="Soft target; runs exceeding this register a wall_warning.",
    )

    model_config = {"frozen": True}


class BenchManifest(BaseModel):
    id: str
    version: str = "1.0"
    description: str = ""
    cases: list[BenchCase]

    model_config = {"frozen": True}


# ─── Scoring ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CaseScore:
    """5-axis score for one case."""

    case_id: str
    correctness: bool | None  # None = not scored (no expected_output_match)
    tool_call_jaccard: float  # 0..1
    cost_usd: float | None  # None = no priced model call (unpriced), never 0.0
    wall_seconds: float
    wall_warning: bool  # exceeded case's max_wall_seconds
    error: str | None  # populated on infrastructure error (excluded from rates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "correctness": self.correctness,
            "tool_call_jaccard": self.tool_call_jaccard,
            "cost_usd": self.cost_usd,
            "wall_seconds": self.wall_seconds,
            "wall_warning": self.wall_warning,
            "error": self.error,
        }


@dataclass(frozen=True)
class BenchSummary:
    """Aggregate of all case scores."""

    run_id: str
    manifest_id: str
    started_at: str
    completed_at: str
    case_count: int
    correctness_rate: float  # cases with correctness=True / cases scored
    avg_tool_jaccard: float
    cost_p50: float | None  # over the cases that had a price; None when none did
    cost_p95: float | None
    wall_p50: float
    wall_p95: float
    infrastructure_errors: int
    cases: list[CaseScore]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "manifest_id": self.manifest_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "case_count": self.case_count,
            "correctness_rate": self.correctness_rate,
            "avg_tool_jaccard": self.avg_tool_jaccard,
            "cost_p50": self.cost_p50,
            "cost_p95": self.cost_p95,
            "wall_p50": self.wall_p50,
            "wall_p95": self.wall_p95,
            "infrastructure_errors": self.infrastructure_errors,
            "cases": [c.to_dict() for c in self.cases],
        }


def jaccard(a: list[str], b: list[str]) -> float:
    """Order-agnostic similarity. 1.0 = identical sets; 0.0 = disjoint."""
    if not a and not b:
        return 1.0
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union > 0 else 0.0


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile. p ∈ [0, 100]."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(sorted_v) - 1)
    weight = k - lo
    return sorted_v[lo] * (1 - weight) + sorted_v[hi] * weight


def score_case(
    case: BenchCase,
    actual_response: str,
    actual_tool_calls: list[str],
    cost_usd: float | None,
    wall_seconds: float,
    error: str | None = None,
) -> CaseScore:
    """Build a CaseScore from a case + the runner's observed result."""
    correctness: bool | None
    if case.expected_output_match is None:
        correctness = None
    else:
        # Plain substring match. Regex support would be a one-line
        # addition if it is ever needed.
        correctness = case.expected_output_match.lower() in actual_response.lower()
    jacc = jaccard(case.expected_tool_calls, actual_tool_calls)
    return CaseScore(
        case_id=case.id,
        correctness=correctness,
        tool_call_jaccard=jacc,
        cost_usd=cost_usd,
        wall_seconds=wall_seconds,
        wall_warning=wall_seconds > case.max_wall_seconds,
        error=error,
    )


def summarize(
    run_id: str,
    manifest: BenchManifest,
    case_scores: list[CaseScore],
    started_at: str,
    completed_at: str,
) -> BenchSummary:
    scored = [c for c in case_scores if c.error is None]
    infra_errors = len(case_scores) - len(scored)
    correctness_scored = [c for c in scored if c.correctness is not None]
    if correctness_scored:
        correct = sum(1 for c in correctness_scored if c.correctness)
        correctness_rate = correct / len(correctness_scored)
    else:
        correctness_rate = 0.0
    jacc_values = [c.tool_call_jaccard for c in scored]
    # Only priced cases: an unpriced case is not a free one, so it must not pull
    # the percentiles toward zero. With none priced the percentile is None.
    cost_values = [c.cost_usd for c in scored if c.cost_usd is not None]
    wall_values = [c.wall_seconds for c in scored]
    return BenchSummary(
        run_id=run_id,
        manifest_id=manifest.id,
        started_at=started_at,
        completed_at=completed_at,
        case_count=len(manifest.cases),
        correctness_rate=correctness_rate,
        avg_tool_jaccard=(sum(jacc_values) / len(jacc_values)) if jacc_values else 0.0,
        cost_p50=percentile(cost_values, 50) if cost_values else None,
        cost_p95=percentile(cost_values, 95) if cost_values else None,
        wall_p50=percentile(wall_values, 50),
        wall_p95=percentile(wall_values, 95),
        infrastructure_errors=infra_errors,
        cases=case_scores,
    )


# ─── Persistence ─────────────────────────────────────────────────────


class BenchRunStore:
    """Sqlite-backed store for benchmark run records. Additive schema —
    no existing table is touched; a new file `benchmark_runs.db` lives
    next to memory.db / hooks.db / jobs.db in the data root."""

    def __init__(self, data_root: Path | None = None) -> None:
        root = data_root or self._resolve_data_root()
        root.mkdir(parents=True, exist_ok=True)
        self._db_path = root / "benchmark_runs.db"
        self._lock = threading.Lock()
        self._init_schema()

    @staticmethod
    def _resolve_data_root() -> Path:
        from os import environ
        return Path(environ.get("PHANTOM_DATA_ROOT", str(DEFAULT_DATA_ROOT)))

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._db_path, isolation_level=None)
        c.row_factory = sqlite3.Row
        return c

    def _init_schema(self) -> None:
        with self._lock, self._conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS benchmark_runs (
                    run_id           TEXT PRIMARY KEY,
                    manifest_id      TEXT NOT NULL,
                    started_at       TEXT NOT NULL,
                    completed_at     TEXT NOT NULL,
                    summary_json     TEXT NOT NULL,
                    router_preset    TEXT
                )
            """)
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_bench_manifest "
                "ON benchmark_runs(manifest_id, started_at DESC)"
            )

    def record(self, summary: BenchSummary, router_preset: str | None = None) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO benchmark_runs (run_id, manifest_id, "
                "started_at, completed_at, summary_json, router_preset) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    summary.run_id, summary.manifest_id,
                    summary.started_at, summary.completed_at,
                    json.dumps(summary.to_dict()),
                    router_preset,
                ),
            )

    def list_recent(self, limit: int | None = None) -> list[dict[str, Any]]:
        """List recent benchmark runs.

        No default limit.
        """
        eff_limit = -1 if (limit is None or int(limit) <= 0) else int(limit)
        with self._conn() as c:
            rows = c.execute(
                "SELECT run_id, manifest_id, started_at, completed_at, "
                "router_preset FROM benchmark_runs "
                "ORDER BY started_at DESC LIMIT ?",
                (eff_limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM benchmark_runs WHERE run_id = ?", (run_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": row["run_id"],
            "manifest_id": row["manifest_id"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "router_preset": row["router_preset"],
            "summary": json.loads(row["summary_json"]),
        }


# Module-level singleton accessor.
_bench_store: BenchRunStore | None = None


def set_bench_store(store: BenchRunStore | None) -> None:
    global _bench_store
    _bench_store = store


def bench_store() -> BenchRunStore | None:
    return _bench_store


# ─── Now-ISO helper ──────────────────────────────────────────────────


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
