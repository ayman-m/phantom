---
id: XQL-718-0b2f6c2a
title: Endpoints not seen in last 7 days (potentially offline)
category: detection
dataset: endpoints
tags:
  - filter
  - fields
  - sort
  - limit
  - endpoints
---

# Endpoints not seen in last 7 days (potentially offline)

**Dataset**: `endpoints`

```sql
dataset = endpoints
| filter endpoint_status != "CONNECTED"
| fields endpoint_name, endpoint_status, operating_system, last_seen, agent_version
| sort asc last_seen
| limit 10
```

## When to use

Endpoints whose status is not CONNECTED (e.g. CONNECTION_LOST, DISCONNECTED). Useful for identifying agents that may have been uninstalled, taken offline by attackers, or have networking issues.

## Variations

_(No variations are documented for this entry.)_
