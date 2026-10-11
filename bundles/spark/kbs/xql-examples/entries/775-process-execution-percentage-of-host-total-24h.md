---
id: XQL-775-841db690
title: Process execution percentage of host total (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - windowcomp
  - alter
  - sort
  - limit
  - xdr_data
  - process
  - math
---

# Process execution percentage of host total (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| comp count() as cnt by agent_hostname, action_process_image_name
| windowcomp sum(cnt) by agent_hostname as host_total
| alter pct = multiply(divide(cnt, host_total), 100)
| sort desc pct
| limit 10
```

## When to use

Each process's share of its host's total execution count. Single dominant process (>50%) on a host often indicates loop / batch activity worth investigating.

## Variations

_(No variations are documented for this entry.)_
