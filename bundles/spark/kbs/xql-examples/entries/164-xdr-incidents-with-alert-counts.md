---
id: XQL-164-xdr-incidents-with-alert-counts
title: Cortex XDR — incidents with alert counts and severity (XDR pattern)
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - sort
  - limit
  - xdr_data
  - xdr-pattern
---

# Cortex XDR — incidents with alert counts and severity

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = ENUM.INCIDENT
| filter _time > to_timestamp(current_time() - duration("P7D"))
| comp count() as alert_count, max(severity) as max_severity by incident_id, incident_name, status
| sort desc alert_count
| limit 50
```

## When to use

Operator asks variants of:

- "what incidents had the most alerts this week?"
- "list incidents grouped by how noisy they were"
- "show me incidents with their alert counts so I can triage"

For listing incidents with their per-incident details (severity, host, alert summaries), prefer the `cortex-xdr/get_cases_and_issues` connector tool — it wraps `POST /public_api/v1/incidents/get_incidents` and returns the same per-incident shape XDR's incident UI shows. This XQL pattern is useful when you want an aggregated *cross-incident* view that the Public API doesn't directly support.

## Variations

- Group by status only: `| comp count() as incident_count by status` — quick "how many in each lifecycle state" snapshot.
- Time-bucket: `| bin _time span=1d as bucket | comp count() by bucket, status` — daily incident volume trend.
- Filter to unresolved: `| filter status not in ("resolved_threat_handled", "resolved_known_issue", "resolved_false_positive")`.
- Add an endpoint dimension: include `agent_hostname` in the `by` list to see which hosts generated the most incidents.

## Source

Pattern derived from the Cortex XDR Public API (`get_incidents`) + the XDR incident-management documentation. Validate against your tenant — `event_type = ENUM.INCIDENT` records and the per-incident schema vary by XDR release; on some tenants the parent-incident records live in a separate dataset (e.g. `xdr_incidents`). For canonical Public API access use `cortex-xdr/get_cases_and_issues`.
