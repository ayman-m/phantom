---
id: XQL-822-fd98386e
title: Process activity duration per host (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - alter
  - sort
  - limit
  - xdr_data
  - process
  - timestamp_diff
---

# Process activity duration per host (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| comp min(_time) as first_seen, max(_time) as last_seen, count() as cnt by agent_hostname
| alter duration_minutes = divide(timestamp_diff(last_seen, first_seen, "MINUTE"), 1)
| sort desc cnt
| limit 10
```

## When to use

Per-host first/last process time + active duration in minutes. Uses `timestamp_diff(end, start, unit)` for time arithmetic on date fields.

## Variations

_(No variations are documented for this entry.)_
