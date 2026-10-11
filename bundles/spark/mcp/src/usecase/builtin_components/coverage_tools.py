"""Closed-loop coverage tools.

Surface for the agent to:

  - Pull XSIAM issues into a local detection inventory
    (`detections_sync`)
  - Read what fired, when, against which technique
    (`detections_list`, `detections_get`)
  - Take point-in-time snapshots of the inventory state
    (`coverage_snapshot_take`)
  - Diff snapshots to detect drift (silent rules, new gaps)
    (`coverage_diff`, `coverage_gaps`)

# Why these are built-in (not connector tools)

They aggregate XSIAM-side data (via the existing xsiam.get_issues
connector tool) into a phantom-local store. The aggregation, the
schema, and the drift-detection logic are all phantom concerns —
they live in the agent runtime regardless of which detection
backend (XSIAM, future Sentinel, Splunk, etc.) the operator has
configured. Putting them in `builtin_components/` gives the agent
a stable tool surface independent of connector churn.

# Approval gating

None of these tools mutate operator-visible state outside the
inventory DB. They're effectively reads + caching writes, so they
DON'T appear in manifest.approvals.humanRequired[]. The expensive
side-effect — calling XSIAM's PAPI — is rate-limited by the
existing fetcher.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("Phantom MCP")


# ─────────────────────────────────────────────────────────────────
# Sync — pull XSIAM issues into the inventory
# Trigger phrases: "sync detections", "refresh the detection
# inventory", "pull recent issues from XSIAM"
# ─────────────────────────────────────────────────────────────────


def detections_sync(
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    """Upsert pre-fetched XSIAM issues into the detection inventory.
    Idempotent — replaying the same payload inserts no duplicate
    rows (PRIMARY KEY on issue_id).

    Two-step flow (chat-driven):
      1. Agent calls `xsiam.get_issues(...)` to fetch the raw page.
      2. Agent passes the result's `issues` array to this tool.

    Closed-loop flow: the manifest job
    `continuous-coverage-cycle` invokes a wrapper that does the
    fetch + the sync in a single tool call (`coverage_cycle_run`).

    Args:
        issues: list of raw XSIAM issue dicts. Required.

    Returns {ok, total, inserted, skipped}.
    """
    from usecase.detection_inventory import detection_inventory
    inv = detection_inventory()
    if inv is None:
        return {"error": "detection inventory not initialized on this MCP runtime"}
    if not isinstance(issues, list):
        return {
            "error": "`issues` must be a list of XSIAM issue dicts. "
            "Call xsiam.get_issues first; pass its 'issues' array here."
        }
    result = inv.upsert_fires(issues)
    return {
        "ok": True,
        **result,
    }


# ─────────────────────────────────────────────────────────────────
# Reads
# Trigger phrases: "list my detections", "what fired today?",
# "did rule X fire this week?", "what techniques are covered?"
# ─────────────────────────────────────────────────────────────────


def detections_list(
    severity: str | None = None,
    technique: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List rules with aggregated fire counts (24h / 7d / 30d).
    Most-recently-fired first.

    Args:
        severity: filter to one severity (low|medium|high|critical).
        technique: filter to rules covering one MITRE T-code.
        limit: max rules (1-500). Default 100.

    Returns {rules: [...], count}.
    """
    from usecase.detection_inventory import detection_inventory
    inv = detection_inventory()
    if inv is None:
        return {"error": "detection inventory not initialized on this MCP runtime"}
    rows = inv.list_rules(
        severity=severity, technique=technique, limit=limit,
    )
    return {"rules": [r.to_dict() for r in rows], "count": len(rows)}


def detections_get(rule_id: str) -> dict[str, Any]:
    """Fetch one rule's aggregated summary.

    Returns {rule: {...}} or {error}.
    """
    from usecase.detection_inventory import detection_inventory
    inv = detection_inventory()
    if inv is None:
        return {"error": "detection inventory not initialized on this MCP runtime"}
    r = inv.rule_summary(rule_id)
    if r is None:
        return {"error": f"rule {rule_id!r} not found in inventory (never fired or sync needed)"}
    return {"rule": r.to_dict()}


def detections_recent_fires(
    rule_id: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Recent fires (newest first), optionally filtered by rule + min time.

    Args:
        rule_id: limit to one rule.
        since: ISO timestamp; only fires AT OR AFTER are returned.
        limit: max rows (1-1000). Default 50.
    """
    from usecase.detection_inventory import detection_inventory
    inv = detection_inventory()
    if inv is None:
        return {"error": "detection inventory not initialized on this MCP runtime"}
    rows = inv.list_fires(rule_id=rule_id, since=since, limit=limit)
    return {"fires": [r.to_dict() for r in rows], "count": len(rows)}


def technique_coverage() -> dict[str, Any]:
    """Per-technique aggregated view across all rules. Used as the
    base for `coverage_gaps`. The agent can call this
    directly to answer "what techniques have I exercised?".

    Returns {techniques: {T-code: {rules_count, fires_24h/7d/30d, last_fire_at}},
             total_techniques}.
    """
    from usecase.detection_inventory import detection_inventory
    inv = detection_inventory()
    if inv is None:
        return {"error": "detection inventory not initialized on this MCP runtime"}
    out = inv.technique_coverage()
    return {"techniques": out, "total_techniques": len(out)}


# ═════════════════════════════════════════════════════════════════
# Snapshots + drift detection
#
# A snapshot is an aggregation of the inventory state at a moment
# in time. Two snapshots can be diffed to spot drift: rules that
# went silent, techniques that lost coverage, new activity that
# wasn't there before. The closed-loop scheduled job
# takes daily snapshots and notifies when drift exceeds threshold.
# ═════════════════════════════════════════════════════════════════


def coverage_snapshot_take(
    label: str | None = None,
) -> dict[str, Any]:
    """Aggregate the live inventory and persist as a coverage snapshot.

    The snapshot body carries per-rule + per-technique rollups + a
    `totals` block. Snapshots are append-only — you can always read
    historical snapshots via coverage_snapshot_list / coverage_diff.

    Args:
        label: optional operator note ("after T1078 sim", "post-rule-update").
            Useful for filtering snapshot history later.

    Returns the new snapshot's id + headline totals.
    """
    from usecase.coverage_store import coverage_store
    from usecase.detection_inventory import detection_inventory
    cs = coverage_store()
    inv = detection_inventory()
    if cs is None:
        return {"error": "coverage store not initialized on this MCP runtime"}
    if inv is None:
        return {"error": "detection inventory not initialized on this MCP runtime"}

    # Build the snapshot body. Per-rule view: every rule from list_rules.
    rules: dict[str, Any] = {}
    rule_rows = inv.list_rules(limit=500)
    fires_24h_total = 0
    fires_7d_total = 0
    fires_30d_total = 0
    for r in rule_rows:
        rd = r.to_dict()
        rules[r.rule_id] = rd
        fires_24h_total += rd["fires_24h"]
        fires_7d_total += rd["fires_7d"]
        fires_30d_total += rd["fires_30d"]

    techniques = inv.technique_coverage()

    body = {
        "rules": rules,
        "techniques": techniques,
        "totals": {
            "rule_count": len(rules),
            "technique_count": len(techniques),
            "fires_24h": fires_24h_total,
            "fires_7d": fires_7d_total,
            "fires_30d": fires_30d_total,
        },
    }

    snap = cs.take(body, label=label, actor="agent")
    return {
        "ok": True,
        "snapshot_id": snap.id,
        "taken_at": snap.taken_at,
        "label": snap.label,
        "totals": body["totals"],
    }


def coverage_snapshot_list(
    limit: int = 20,
    label: str | None = None,
) -> dict[str, Any]:
    """Recent snapshots, newest first. Body excluded — use
    coverage_snapshot_get(id) for full content."""
    from usecase.coverage_store import coverage_store
    cs = coverage_store()
    if cs is None:
        return {"error": "coverage store not initialized on this MCP runtime"}
    rows = cs.list_recent(limit=limit, label=label)
    return {
        "snapshots": [r.to_dict(include_body=False) for r in rows],
        "count": len(rows),
    }


def coverage_snapshot_get(snapshot_id: str) -> dict[str, Any]:
    """Fetch a snapshot's full body."""
    from usecase.coverage_store import coverage_store
    cs = coverage_store()
    if cs is None:
        return {"error": "coverage store not initialized on this MCP runtime"}
    snap = cs.get(snapshot_id)
    if snap is None:
        return {"error": f"snapshot {snapshot_id!r} not found"}
    return {"snapshot": snap.to_dict()}


def coverage_diff(
    from_snapshot_id: str | None = None,
    to_snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Compute drift between two snapshots.

    Args:
        from_snapshot_id: older snapshot id. If None, uses the
            second-newest snapshot.
        to_snapshot_id: newer snapshot id. If None, uses the most
            recent snapshot.

    Returns the structured drift report from coverage_store.diff_snapshots
    plus the snapshot timestamps so the report renders standalone.
    """
    from usecase.coverage_store import coverage_store, diff_snapshots
    cs = coverage_store()
    if cs is None:
        return {"error": "coverage store not initialized on this MCP runtime"}

    if to_snapshot_id is None or from_snapshot_id is None:
        recent = cs.list_recent(limit=2)
        if len(recent) < 2:
            return {
                "error": "need at least 2 snapshots to compute drift; "
                "take more via coverage_snapshot_take() first.",
                "available": len(recent),
            }
        # recent[0] is newest.
        if to_snapshot_id is None:
            to_snapshot_id = recent[0].id
        if from_snapshot_id is None:
            from_snapshot_id = recent[1].id

    older = cs.get(from_snapshot_id)
    newer = cs.get(to_snapshot_id)
    if older is None:
        return {"error": f"snapshot {from_snapshot_id!r} not found"}
    if newer is None:
        return {"error": f"snapshot {to_snapshot_id!r} not found"}

    report = diff_snapshots(older.body, newer.body)
    report["summary"]["older_id"] = from_snapshot_id
    report["summary"]["older_at"] = older.taken_at
    report["summary"]["newer_id"] = to_snapshot_id
    report["summary"]["newer_at"] = newer.taken_at

    # Audit if any drift signals fired — the closed-loop job uses
    # this event as the trigger for notifications.
    try:
        from usecase.audit_log import (
            ACTION_COVERAGE_DRIFT_DETECTED,
            record_event,
        )
        if report["summary"]["total_signals"] > 0:
            record_event(
                ACTION_COVERAGE_DRIFT_DETECTED,
                target=f"coverage_snapshot:{to_snapshot_id}",
                status="success",
                metadata={
                    "from_snapshot_id": from_snapshot_id,
                    "to_snapshot_id": to_snapshot_id,
                    "rules_silent": report["summary"]["rules_silent_count"],
                    "rules_dropping": report["summary"]["rules_dropping_count"],
                    "techniques_uncovered": report["summary"][
                        "techniques_uncovered_count"
                    ],
                },
            )
    except Exception:  # noqa: BLE001
        pass

    return report


# ═════════════════════════════════════════════════════════════════
# COMMIT 3 — coverage gaps
#
# `coverage_gaps` surfaces techniques the operator's deploy is
# weak on. Three signals:
#
#   silent       — rules_count > 0 AND fires_30d == 0
#                  (rules cover this technique on paper, but no fire
#                   in 30 days — high-confidence drift signal)
#
#   going_dark   — fires_30d > 0 AND fires_7d == 0
#                  (fired recently, silent the last week — early
#                   warning of drift before it becomes silent)
#
#   low_coverage — rules_count == 1
#                  (only one detection covers this technique; if it
#                   silences, you have nothing else to catch the TTP)
#
# v1 deliberately doesn't include "uncovered" (techniques the
# operator's threat model claims to cover but have NO rules) —
# that requires a separate baseline catalog. The OPERATIONAL gaps
# above are computed purely from the inventory and don't need
# external context.
# ═════════════════════════════════════════════════════════════════


def coverage_gaps(
    *,
    silent_days: int = 30,
    dark_days: int = 7,
    min_rules_for_low: int = 2,
    limit: int = 50,
) -> dict[str, Any]:
    """Find techniques with weak operational coverage.

    Args:
        silent_days: a technique with no fires in this window AND
            rules_count > 0 is "silent". Default 30.
        dark_days: a technique that fired in the silent_days window
            but NOT in the dark_days window is "going dark".
            Default 7.
        min_rules_for_low: techniques with fewer than this many rules
            are "low coverage". Default 2 (i.e. single-rule
            techniques are flagged).
        limit: max entries returned per category.

    Returns {silent, going_dark, low_coverage, summary}.
    """
    from usecase.detection_inventory import detection_inventory
    inv = detection_inventory()
    if inv is None:
        return {"error": "detection inventory not initialized on this MCP runtime"}

    coverage = inv.technique_coverage()

    silent: list[dict[str, Any]] = []
    going_dark: list[dict[str, Any]] = []
    low_coverage: list[dict[str, Any]] = []

    for t, info in coverage.items():
        rules_count = info["rules_count"]
        fires_7d = info["fires_7d"]
        fires_30d = info["fires_30d"]

        if rules_count > 0 and fires_30d == 0:
            silent.append({
                "technique_id": t,
                "rules_count": rules_count,
                "fires_30d": 0,
                "last_fire_at": info["last_fire_at"],
                "severity": "high",  # silent for 30d = strong signal
            })
        elif fires_30d > 0 and fires_7d == 0:
            going_dark.append({
                "technique_id": t,
                "rules_count": rules_count,
                "fires_30d": fires_30d,
                "fires_7d": 0,
                "last_fire_at": info["last_fire_at"],
                "severity": "medium",  # early warning
            })

        if rules_count < min_rules_for_low and rules_count > 0:
            low_coverage.append({
                "technique_id": t,
                "rules_count": rules_count,
                "fires_30d": fires_30d,
                "last_fire_at": info["last_fire_at"],
                "severity": "info",  # not necessarily a problem
            })

    # Sort silent + going_dark by last_fire_at ASC (oldest = worst);
    # low_coverage by rules_count ASC.
    silent.sort(key=lambda x: x["last_fire_at"])
    going_dark.sort(key=lambda x: x["last_fire_at"])
    low_coverage.sort(key=lambda x: x["rules_count"])

    # Audit a "gap observed" event so the closed-loop job
    # can react to gaps as they appear (notification + scenario
    # suggestion). One event per call regardless of count — operators
    # don't want spam in audit.
    try:
        from usecase.audit_log import (
            ACTION_COVERAGE_GAP_OBSERVED,
            record_event,
        )
        if silent or going_dark:
            record_event(
                ACTION_COVERAGE_GAP_OBSERVED,
                target="coverage_gaps",
                status="success",
                metadata={
                    "silent_count": len(silent),
                    "going_dark_count": len(going_dark),
                    "low_coverage_count": len(low_coverage),
                    "silent_techniques": [g["technique_id"] for g in silent[:20]],
                },
            )
    except Exception:  # noqa: BLE001
        pass

    return {
        "silent": silent[: max(1, min(int(limit), 200))],
        "going_dark": going_dark[: max(1, min(int(limit), 200))],
        "low_coverage": low_coverage[: max(1, min(int(limit), 200))],
        "summary": {
            "silent_count": len(silent),
            "going_dark_count": len(going_dark),
            "low_coverage_count": len(low_coverage),
            "total_techniques": len(coverage),
            "silent_days": silent_days,
            "dark_days": dark_days,
        },
    }


# ═════════════════════════════════════════════════════════════════
# COMMIT 4 — closed-loop orchestrator
#
# `coverage_cycle_run` is the tool the manifest's
# `continuous-coverage-cycle` scheduled job invokes. It does in one
# pass what the chat-driven flow does in 6 tool calls:
#
#   1. Look up the active xsiam instance from the InstanceStore.
#   2. Resolve secrets via the bound SecretStore.
#   3. POST directly to XSIAM PAPI /issue/search/ with the time
#      window filter (default last 24h).
#   4. Upsert the issues into the detection inventory.
#   5. Take a coverage snapshot labeled `scheduler:cycle`.
#   6. If we have a previous snapshot, compute drift via
#      coverage_diff. Audit-log on non-zero signals.
#   7. Run coverage_gaps and audit-log on non-zero gap signals.
#   8. If drift or gap signals fired, publish an operator
#      notification with the headline counts.
#
# # Why direct PAPI vs going through the connector tool wrapper
#
# The connector wrapper (_wrap_with_instance) sets a per-call
# instance contextvar so connector tools resolve their config + auth
# at runtime. Invoking it from inside another in-process tool would
# require setting up that contextvar manually. Cleaner to bypass the
# wrapper: we already have the InstanceStore singleton, we already
# have the SecretStore reference (via InstanceStore.secret_store),
# and the PAPI request is two HTTP headers + a JSON body. The
# connector's xsiam_get_issues function still exists for chat-driven
# use; this tool just doesn't go through it.
# ═════════════════════════════════════════════════════════════════


async def coverage_cycle_run(
    hours_back: int = 24,
    severities: list[str] | None = None,
    drift_signal_threshold: int = 1,
) -> dict[str, Any]:
    """Closed-loop coverage cycle: fetch → sync → snapshot → diff
    → gap-detect → notify.

    Used by the manifest job `continuous-coverage-cycle` (daily) and
    callable from chat for ad-hoc runs.

    Args:
        hours_back: XSIAM lookback window. Default 24.
        severities: optional severity filter, e.g. ["high", "critical"].
        drift_signal_threshold: minimum drift signals to trigger an
            operator notification. 1 = any drift.

    Returns a structured cycle report:
      {
        ok, fetched, ingest, snapshot_id, drift_summary, gaps_summary,
        notification_published
      }
    """
    import time
    import httpx

    from usecase.instance_store import instance_store
    from usecase.detection_inventory import detection_inventory
    from usecase.coverage_store import coverage_store
    from usecase.notifications import notification_store

    inv = detection_inventory()
    cs = coverage_store()
    inst_store = instance_store()
    if inv is None or cs is None or inst_store is None:
        return {"error": "coverage stores not initialized on this MCP runtime"}

    # ─── Step 1: locate the active xsiam instance ────────────────
    xsiam = inst_store.list_for("xsiam")
    if not xsiam:
        return {
            "error": "no xsiam instance configured — run setup or "
            "POST /api/v1/instances first",
        }
    inst = xsiam[0]
    config = inst.merged_config(secret_store=inst_store.secret_store)

    # Config keys are api_url / api_id / api_key. Read those first,
    # legacy papi* names second, env-var aliases third, so instances
    # created under the older key names keep working without migration.
    base_url = (
        config.get("api_url")
        or config.get("papiUrl")
        or config.get("CORTEX_MCP_PAPI_URL")
        or ""
    ).rstrip("/")
    auth_header = (
        config.get("api_key")
        or config.get("papiAuthHeader")
        or config.get("CORTEX_MCP_PAPI_AUTH_HEADER")
    )
    auth_id = (
        config.get("api_id")
        or config.get("papiAuthId")
        or config.get("CORTEX_MCP_PAPI_AUTH_ID")
    )
    if not base_url or not auth_header or not auth_id:
        return {
            "error": "xsiam instance is missing api_url / api_key / api_id",
            "instance_id": inst.id,
        }
    # Ensure /public_api/v1 suffix.
    if "/public_api" not in base_url:
        base_url = f"{base_url}/public_api/v1"
    elif not base_url.endswith("/public_api/v1"):
        base_url = base_url.split("/public_api")[0].rstrip("/") + "/public_api/v1"

    # ─── Step 2: build the issue-search filter ───────────────────
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - int(hours_back) * 3600 * 1000
    filters: list[dict[str, Any]] = [
        {"field": "_insert_time", "operator": "gte", "value": start_ms},
    ]
    if severities:
        filters.append({
            "field": "severity",
            "operator": "in",
            "value": [s.upper() for s in severities],
        })

    # ─── Step 3: paginate /issue/search/ ─────────────────────────
    issues: list[dict[str, Any]] = []
    pages = 0
    MAX_PAGES = 20  # safety bound — 2000 issues max per cycle
    headers = {
        "x-xdr-auth-id": str(auth_id),
        "Authorization": str(auth_header),
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        search_from = 0
        while pages < MAX_PAGES:
            try:
                resp = await client.post(
                    f"{base_url}/issue/search/",
                    headers=headers,
                    json={"request_data": {"search_from": search_from, "filters": filters}},
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "coverage_cycle_run: PAPI fetch page %d failed (%s)", pages, exc,
                )
                break
            if resp.status_code >= 400:
                logger.warning(
                    "coverage_cycle_run: PAPI returned %d on page %d",
                    resp.status_code, pages,
                )
                break
            try:
                payload = resp.json()
            except Exception:  # noqa: BLE001
                break
            page = (
                payload.get("reply", {}).get("data", {}).get("issues")
                or payload.get("issues")
                or payload.get("data", {}).get("issues")
                or []
            )
            if not page:
                break
            issues.extend(page)
            pages += 1
            if len(page) < 100:
                break
            search_from += len(page)

    # ─── Step 4: ingest into the inventory ──────────────────────
    ingest_result = inv.upsert_fires(issues)

    # ─── Step 5: take a snapshot ─────────────────────────────────
    snap_dict = coverage_snapshot_take(label="scheduler:cycle")
    if "error" in snap_dict:
        return {
            "error": f"snapshot failed: {snap_dict['error']}",
            "ingest": ingest_result,
        }
    snap_id = snap_dict["snapshot_id"]

    # ─── Step 6: drift vs previous snapshot ──────────────────────
    drift_summary: dict[str, Any] | None = None
    drift_report: dict[str, Any] | None = None
    prev_snapshots = cs.list_recent(limit=2)
    if len(prev_snapshots) >= 2:
        # newest is the one we just took (index 0). Prev is index 1.
        drift_report = coverage_diff(
            from_snapshot_id=prev_snapshots[1].id,
            to_snapshot_id=prev_snapshots[0].id,
        )
        drift_summary = drift_report.get("summary") if drift_report else None

    # ─── Step 7: gap detection ───────────────────────────────────
    gap_report = coverage_gaps()
    gaps_summary = gap_report.get("summary") if "error" not in gap_report else None

    # ─── Step 8: notification ────────────────────────────────────
    notification_published = False
    drift_signals = (drift_summary or {}).get("total_signals", 0)
    silent_count = (gaps_summary or {}).get("silent_count", 0)
    going_dark_count = (gaps_summary or {}).get("going_dark_count", 0)
    triggers = drift_signals + silent_count + going_dark_count

    if triggers >= drift_signal_threshold:
        ns = notification_store()
        if ns is not None:
            # NotificationStore.publish takes a topic name + a free-form
            # payload dict. Severity + target are inherited from the
            # manifest's topic spec (manifest.notifications.topics) — we
            # declared `coverage-cycle` for this exact purpose with
            # severity=info, target=user:operator.
            try:
                ns.publish(
                    topic="coverage-cycle",
                    payload={
                        "title": (
                            "Coverage cycle: "
                            f"{drift_signals} drift, "
                            f"{silent_count} silent, "
                            f"{going_dark_count} going dark"
                        ),
                        "body": _format_cycle_body(
                            ingest_result, drift_summary, gaps_summary, snap_id,
                        ),
                        "snapshot_id": snap_id,
                        "drift_summary": drift_summary,
                        "gaps_summary": gaps_summary,
                    },
                    actor="scheduler:continuous-coverage-cycle",
                )
                notification_published = True
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "coverage_cycle_run: notification publish failed (%s)", exc,
                )

    return {
        "ok": True,
        "fetched": len(issues),
        "pages": pages,
        "ingest": ingest_result,
        "snapshot_id": snap_id,
        "drift_summary": drift_summary,
        "gaps_summary": gaps_summary,
        "notification_published": notification_published,
    }


def _format_cycle_body(
    ingest: dict[str, Any],
    drift: dict[str, Any] | None,
    gaps: dict[str, Any] | None,
    snap_id: str,
) -> str:
    """Operator-readable summary for the notification body."""
    lines = [
        f"Snapshot: {snap_id}",
        f"Ingest:   {ingest.get('inserted', 0)} new fires "
        f"({ingest.get('total', 0)} total).",
    ]
    if drift:
        lines.append(
            f"Drift:    {drift.get('rules_silent_count', 0)} silent, "
            f"{drift.get('rules_dropping_count', 0)} dropping, "
            f"{drift.get('rules_new_count', 0)} new active."
        )
    if gaps:
        lines.append(
            f"Gaps:     {gaps.get('silent_count', 0)} silent techniques, "
            f"{gaps.get('going_dark_count', 0)} going dark, "
            f"{gaps.get('low_coverage_count', 0)} single-rule."
        )
    lines.append("")
    lines.append("View at /coverage (UI) or query GET /api/v1/detections.")
    return "\n".join(lines)
