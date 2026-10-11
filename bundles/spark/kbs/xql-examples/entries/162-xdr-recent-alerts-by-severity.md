---
id: XQL-162-xdr-recent-alerts-by-severity
title: Cortex XDR — recent alerts filtered by severity (XDR pattern)
category: detection
dataset: xdr_data
tags:
  - filter
  - sort
  - limit
  - xdr_data
  - xdr-pattern
---

# Cortex XDR — recent alerts filtered by severity

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = ENUM.ALERT
| filter severity in ("high", "critical")
| filter _time > to_timestamp(current_time() - duration("PT24H"))
| sort desc _time
| limit 100
```

## When to use

Operator asks variants of:

- "show me recent alerts in the last 24 hours"
- "what unresolved high-severity alerts are on the tenant"
- "list critical alerts from yesterday"

The agent dispatches via `cortex-xdr/run_xql_query`. For incident-shaped (parent-of-alerts) queries, prefer `cortex-xdr/get_cases_and_issues` — this XQL is for the flat alert stream.

## Variations

- Swap the severity list: `("medium")`, `("low", "medium")`, `("critical")`.
- Adjust the time window: `PT1H` (last hour), `PT7D` (last week). XDR's `_time` is the alert ingestion timestamp.
- Add an endpoint filter: `| filter agent_hostname = "<host>"`.
- Add a status filter: `| filter status in ("new", "under_investigation")`.

## Source

Pattern derived from the Cortex XDR Public API + Cortex XQL documentation (queryable via Phantom's `cortex-docs/search`, `product=xdr`). Validate against your tenant's `xdr_data` schema before relying on field names — multi-tenant deployments may surface custom alert fields.
