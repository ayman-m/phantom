---
id: XQL-793-88097884
title: Process executions with effective user fallback (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - alter
  - comp
  - sort
  - limit
  - xdr_data
  - user
  - coalesce
---

# Process executions with effective user fallback (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| alter user = coalesce(actor_effective_username, actor_primary_username, "unknown")
| comp count() as cnt by user
| sort desc cnt
| limit 10
```

## When to use

Per-user execution count with `coalesce` to fall back to primary_username when effective is null, then to literal 'unknown'. Robust against missing-data gaps.

## Variations

_(No variations are documented for this entry.)_
