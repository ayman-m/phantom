---
id: XQL-787-e619d553
title: Mean process-execution counts per host (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - limit
  - xdr_data
  - process
  - stats
---

# Mean process-execution counts per host (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| comp count() as host_total by agent_hostname
| comp avg(host_total) as mean_per_host, count() as host_count
| limit 10
```

## When to use

Fleet-level statistic — average process executions per host + total host count. Useful baseline for sizing + outlier-comparison queries.

## Variations

_(No variations are documented for this entry.)_
