"""Benchmark runner.

The benchmark module provides the scaffolding (Pydantic models, scorer,
BenchRunStore); this runner turns it into something operators can
actually fire. Each case in a manifest:

  1. POST `/api/chat` with the case's prompt + router-preset
     model override (when supplied).
  2. Stream the SSE response, collect tool_call events + final text +
     turn-completion meta (cost, wall).
  3. Build a CaseScore via `score_case` from the benchmark module.

The runner runs server-side (in MCP) so it can call back into the
agent's chat route via the same httpx client + auth pattern the
scheduler uses for job dispatches (`_dispatch_chat`).

# Not yet implemented

- `/observability/bench` UI page (run history, compare view, drill-
  down). The runner today emits a JSON summary the operator reads from
  the audit log or the bench_run MCP-tool return value.
- CLI binary `phantom bench run`. Wired via the MCP tool for now;
  operators invoke from chat.
- Scheduled bench job (weekly auto-run). Operators wire today via the
  existing scheduler + bench_run tool.
- Regression-flag integration with release-gating.

# Manifest path resolution

`bench_run(manifest)` accepts either:
  - An absolute / relative path to a YAML file.
  - A bundled-corpus id like `"phantom-soc-v1"` (resolved to
    `bench_cases/<id>.yaml` next to this module).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import yaml

from usecase.benchmark import (
    BenchCase,
    BenchManifest,
    BenchRunStore,
    BenchSummary,
    CaseScore,
    bench_store,
    now_iso,
    score_case,
    summarize,
)

logger = logging.getLogger("Phantom MCP")

DEFAULT_AGENT_INTERNAL_URL = "https://phantom-agent:8080"
CASE_TIMEOUT_S = 300.0  # per-case timeout — overrides BenchCase.max_wall_seconds
                       # only on infrastructure deadlock; the case-side
                       # max_wall_seconds drives wall_warning flag.

BENCH_CASES_DIR = Path(__file__).parent / "bench_cases"


def load_manifest(manifest_ref: str) -> BenchManifest:
    """Resolve `manifest_ref` to a BenchManifest. Accepts:
      - A path to a YAML file (absolute or relative to CWD).
      - A bundled-corpus id (resolved to bench_cases/<id>.yaml).
    Raises ValueError when the file isn't found or doesn't parse."""
    candidates: list[Path] = []
    p = Path(manifest_ref)
    if p.exists():
        candidates.append(p)
    bundled = BENCH_CASES_DIR / f"{manifest_ref}.yaml"
    if bundled.exists():
        candidates.append(bundled)
    bundled_dir = BENCH_CASES_DIR / manifest_ref / "manifest.yaml"
    if bundled_dir.exists():
        candidates.append(bundled_dir)
    if not candidates:
        raise ValueError(
            f"manifest not found: {manifest_ref!r}. Tried path, "
            f"bench_cases/{manifest_ref}.yaml, "
            f"bench_cases/{manifest_ref}/manifest.yaml."
        )
    path = candidates[0]
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ValueError(f"manifest {path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"manifest {path} must be a YAML object at the top level")
    # YAML may wrap in {"manifest": {...}} or be flat. Support both.
    body = raw.get("manifest", raw) if "manifest" in raw or "cases" in raw else raw
    return BenchManifest.model_validate(body)


async def _dispatch_case(
    case: BenchCase,
    router_preset_model: str | None,
    thinking_enabled: bool,
) -> tuple[str, list[str], float, float, str | None]:
    """Fire one case against the agent's /api/chat endpoint. Returns
    (final_response, tool_call_names, cost_usd, wall_seconds, error).

    On infrastructure error (HTTP non-200, timeout, agent unreachable),
    `error` is populated and the other fields are best-effort. Score
    will tag the case as `infrastructure_error`.
    """
    agent_url = os.environ.get(
        "PHANTOM_AGENT_INTERNAL_URL", DEFAULT_AGENT_INTERNAL_URL
    ).rstrip("/")
    chat_endpoint = f"{agent_url}/api/chat"

    body: dict[str, Any] = {"message": case.prompt}
    if router_preset_model:
        body["model"] = router_preset_model
    if thinking_enabled:
        body["thinking"] = True

    text_parts: list[str] = []
    tool_calls: list[str] = []
    cost_usd = 0.0
    started_at = time.time()
    last_error: str | None = None

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(CASE_TIMEOUT_S), verify=False,
        ) as client:
            async with client.stream(
                "POST",
                chat_endpoint,
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                    "X-Phantom-Trigger": "bench",
                },
            ) as resp:
                if resp.status_code != 200:
                    text = (await resp.aread()).decode(errors="replace")
                    last_error = f"agent /api/chat returned {resp.status_code}: {text[:200]}"
                    return ("", [], 0.0, time.time() - started_at, last_error)
                event_type: str | None = None
                async for raw_line in resp.aiter_lines():
                    line = raw_line.rstrip("\r")
                    if not line:
                        event_type = None
                        continue
                    if line.startswith("id: "):
                        continue
                    if line.startswith("event: "):
                        event_type = line[len("event: "):].strip()
                    elif line.startswith("data: "):
                        payload = line[len("data: "):]
                        try:
                            data = json.loads(payload)
                        except json.JSONDecodeError:
                            data = payload
                        if event_type == "text_delta" and isinstance(data, dict):
                            t = data.get("text")
                            if isinstance(t, str):
                                text_parts.append(t)
                        elif event_type == "tool_call" and isinstance(data, dict):
                            name = data.get("tool") or data.get("name")
                            if isinstance(name, str):
                                tool_calls.append(name)
                        elif event_type == "meta" and isinstance(data, dict):
                            c = data.get("cost_usd")
                            if isinstance(c, (int, float)) and c > 0:
                                cost_usd = float(c)
                        elif event_type == "done":
                            break
    except Exception as exc:  # noqa: BLE001
        last_error = f"dispatch failed: {exc}"

    final_response = "".join(text_parts).strip()
    wall_seconds = time.time() - started_at
    return (final_response, tool_calls, cost_usd, wall_seconds, last_error)


async def run_manifest(
    manifest_ref: str,
    *,
    router_preset_model: str | None = None,
    thinking_enabled: bool = False,
    record: bool = True,
) -> BenchSummary:
    """Execute every case in the manifest, return the summary. When
    `record=True` (default), persists to BenchRunStore for later
    retrieval via /api/v1/bench/runs/{id}.

    Args:
      manifest_ref: path or bundled-corpus id (see load_manifest).
      router_preset_model: pass through to body.model on each dispatch
        (e.g. "gemini-2.5-flash" for a Flash bench preset).
      thinking_enabled: pass through to body.thinking.
      record: store the summary in BenchRunStore.
    """
    manifest = load_manifest(manifest_ref)
    run_id = f"bench_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    started_at = now_iso()
    logger.info(
        "BenchRunner starting run %s manifest=%s cases=%d preset=%s",
        run_id, manifest.id, len(manifest.cases),
        router_preset_model or "(router default)",
    )

    case_scores: list[CaseScore] = []
    for case in manifest.cases:
        (resp, tool_calls, cost, wall, error) = await _dispatch_case(
            case, router_preset_model, thinking_enabled,
        )
        score = score_case(
            case=case,
            actual_response=resp,
            actual_tool_calls=tool_calls,
            cost_usd=cost,
            wall_seconds=wall,
            error=error,
        )
        case_scores.append(score)
        logger.info(
            "BenchRunner case=%s correctness=%s jaccard=%.2f cost=$%.4f wall=%.1fs%s",
            case.id, score.correctness, score.tool_call_jaccard,
            score.cost_usd, score.wall_seconds,
            f" error={error}" if error else "",
        )

    completed_at = now_iso()
    summary = summarize(
        run_id=run_id,
        manifest=manifest,
        case_scores=case_scores,
        started_at=started_at,
        completed_at=completed_at,
    )

    if record:
        store = bench_store()
        if store is None:
            # Lazy-init when main.py hasn't wired the singleton yet
            # (e.g. operator-invoked tools before MCP boot has fully
            # finished). Persists to the default location.
            store = BenchRunStore()
        store.record(summary, router_preset=router_preset_model)
        logger.info(
            "BenchRunner recorded run %s: correctness=%.1f%% avg_jaccard=%.2f cost_p50=$%.4f wall_p50=%.1fs",
            run_id,
            summary.correctness_rate * 100,
            summary.avg_tool_jaccard,
            summary.cost_p50,
            summary.wall_p50,
        )

    return summary


def run_manifest_sync(
    manifest_ref: str,
    *,
    router_preset_model: str | None = None,
    thinking_enabled: bool = False,
    record: bool = True,
) -> BenchSummary:
    """Sync convenience wrapper around `run_manifest`. The MCP tool's
    sync execution path uses this; chat-driven dispatches happen on
    the agent's event loop, so the sync wrapper boots its own loop
    only when one isn't already running."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            run_manifest(
                manifest_ref,
                router_preset_model=router_preset_model,
                thinking_enabled=thinking_enabled,
                record=record,
            )
        )
    # Running loop already exists — fire as a task + block (rare for
    # the MCP-tool path but useful in tests).
    fut = asyncio.run_coroutine_threadsafe(
        run_manifest(
            manifest_ref,
            router_preset_model=router_preset_model,
            thinking_enabled=thinking_enabled,
            record=record,
        ),
        loop,
    )
    return fut.result(timeout=CASE_TIMEOUT_S * 100)  # generous outer cap
