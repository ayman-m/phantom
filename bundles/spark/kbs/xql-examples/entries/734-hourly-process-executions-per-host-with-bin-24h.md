---
id: XQL-734-b7b3c63a
title: Hourly process executions per host with bin (24h)
category: detection
dataset: xdr_data
tags:
  - filter
  - bin
  - comp
  - sort
  - limit
  - xdr_data
  - process
---

# Hourly process executions per host with bin (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| bin _time span = 1h
| comp count() as exec_count by _time, agent_hostname
| sort desc _time, agent_hostname
| limit 10
```

## When to use

Time-bucketed process execution rate per host. The `bin _time span = 1h` stage creates hourly buckets — useful for finding unusual spikes in process activity timewise.

## Variations

_(No variations are documented for this entry.)_
