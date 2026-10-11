---
id: XQL-163-xdr-process-events-by-hostname
title: Cortex XDR — process events on a specific endpoint (XDR pattern)
category: detection
dataset: xdr_data
tags:
  - filter
  - dedup
  - limit
  - xdr_data
  - xdr-pattern
---

# Cortex XDR — process events on a specific endpoint

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = ENUM.PROCESS
| filter agent_hostname = "win-host-01"
| filter _time > to_timestamp(current_time() - duration("PT1H"))
| dedup actor_process_image_name
| limit 50
```

## When to use

Operator asks variants of:

- "what processes ran on `<hostname>` in the last hour?"
- "show me unique processes on the XDR endpoint after the Caldera operation"
- "list distinct process names on this host"

This is the canonical "what fired on host X" probe — used during Caldera detection-validation (the `cortex-xdr` connector's hero example, per the connector.yaml `run_xql_query` description). The agent dispatches via `cortex-xdr/run_xql_query` after the Caldera operation completes.

## Variations

- Drop `dedup` to see every process invocation chronologically (raw event stream).
- Narrow the time window to align with a known attack window: `_time between to_timestamp(...) and to_timestamp(...)`.
- Filter by process name: `| filter actor_process_image_name in ("powershell.exe", "cmd.exe", "wmic.exe")` for known living-off-the-land binaries.
- Group by user: `| comp count() as event_count by actor_process_image_name, actor_effective_username`.

## Source

Pattern derived from the Cortex XDR Public API documentation + the `cortex-xdr` connector's `run_xql_query` tool description (bundles/spark/connectors/cortex-xdr/connector.yaml). Validate against your tenant — multi-tenant XDR deployments may use different `agent_hostname` formats and the `actor_process_*` field family varies by sensor version.
