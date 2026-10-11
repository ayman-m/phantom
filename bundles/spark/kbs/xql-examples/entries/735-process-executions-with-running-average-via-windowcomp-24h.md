---
id: XQL-735-4757ed35
title: Process executions with running average via windowcomp (24h)
category: detection
dataset: xdr_data
tags:
  - filter
  - bin
  - comp
  - windowcomp
  - sort
  - limit
  - xdr_data
  - process
---

# Process executions with running average via windowcomp (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| bin _time span = 1h
| comp count() as exec_count by _time, agent_hostname
| windowcomp avg(exec_count) by agent_hostname as rolling_avg
| sort desc _time
| limit 10
```

## When to use

Hourly execution counts with a rolling average per host computed via `windowcomp`. Foundation for anomaly-detection queries (compare current count vs rolling baseline).

## Variations

_(No variations are documented for this entry.)_
