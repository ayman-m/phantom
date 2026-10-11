---
id: XQL-717-e9fd6835
title: All endpoints with status + OS + agent version
category: investigation
dataset: endpoints
tags:
  - fields
  - sort
  - limit
  - endpoints
---

# All endpoints with status + OS + agent version

**Dataset**: `endpoints`

```sql
dataset = endpoints
| fields endpoint_name, endpoint_status, operating_system, agent_version, last_seen, ip_address
| sort asc last_seen
| limit 10
```

## When to use

Foundational endpoint inventory query. Returns all managed endpoints sorted by last_seen ascending so the oldest-last-seen entries surface first (stale agents).

## Variations

_(No variations are documented for this entry.)_
