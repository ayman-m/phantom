---
id: XQL-846-eb3ed09d
title: Process activity heat-map by hour-of-day (24h, extract_time)
category: detection
dataset: xdr_data
tags:
  - filter
  - alter
  - comp
  - sort
  - limit
  - xdr_data
  - process
  - extract_time
---

# Process activity heat-map by hour-of-day (24h, extract_time)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| alter hour = extract_time(_time, "HOUR")
| comp count() as executions by hour, agent_hostname
| sort asc agent_hostname, asc hour
| limit 10
```

## When to use

Per-host hour-of-day execution heat map. `extract_time(timestamp, 'HOUR')` returns the hour component (0-23). Off-hours activity is a compromise indicator.

## Variations

_(No variations are documented for this entry.)_
