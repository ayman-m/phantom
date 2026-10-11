---
id: XQL-854-bba99a73
title: Median upload bytes per host (24h, median)
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - sort
  - limit
  - xdr_data
  - network
  - median
---

# Median upload bytes per host (24h, median)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK and action_total_upload > 0
| comp median(action_total_upload) as median_bytes, avg(action_total_upload) as avg_bytes, count() as conn_count by agent_hostname
| sort desc median_bytes
| limit 10
```

## When to use

Per-host MEDIAN upload bytes (more robust to outliers than avg). Median vs avg: close = uniform; median much less than avg = skewed by a few large outliers.

## Variations

_(No variations are documented for this entry.)_
