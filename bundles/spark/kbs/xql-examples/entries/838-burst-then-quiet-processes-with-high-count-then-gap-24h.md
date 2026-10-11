---
id: XQL-838-7dd60402
title: Burst then quiet — processes with high count then gap (24h)
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
  - lag
  - anomaly
---

# Burst then quiet — processes with high count then gap (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| bin _time span = 1h
| comp count() as exec_count by _time, agent_hostname
| windowcomp lag(exec_count) by agent_hostname sort asc _time as prev_hour_count
| filter exec_count > 100 and prev_hour_count < 10
| sort desc _time
| limit 10
```

## When to use

Detects hourly process-execution bursts following quiet periods (current >100, previous <10). Combines `bin` + `comp` + `windowcomp lag()` — the canonical multi-stage anomaly-detection chain.

## Variations

_(No variations are documented for this entry.)_
