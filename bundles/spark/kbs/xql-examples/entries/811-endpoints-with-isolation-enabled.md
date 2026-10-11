---
id: XQL-811-b2d41fea
title: Endpoints with isolation enabled
category: investigation
dataset: endpoints
tags:
  - filter
  - fields
  - sort
  - limit
  - endpoints
---

# Endpoints with isolation enabled

**Dataset**: `endpoints`

```sql
dataset = endpoints
| filter endpoint_isolated = "ISOLATED"
| fields endpoint_name, endpoint_status, operating_system, last_seen, ip_address
| sort desc last_seen
| limit 10
```

## When to use

Currently-isolated endpoints. `endpoint_isolated` is a string with values like NOT_ISOLATED / ISOLATED in this tenant — filter as string equality.

## Variations

_(No variations are documented for this entry.)_
