---
id: XQL-402-df330dfd
title: PANW NGFW | Average Bytes per Session by Source Zone
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - config
  - comp
  - sort
  - panw_ngfw_traffic_raw
  - source:dataset
---

# PANW NGFW | Average Bytes per Session by Source Zone

**Dataset**: `panw_ngfw_traffic_raw`

```sql
config timeframe = 30d
| dataset = panw_ngfw_traffic_raw
| comp avg(bytes_total) as avg_bytes_per_session by from_zone
| sort desc avg_bytes_per_session
```

## When to use

Calculates the average number of Next-Generation-Firewall (NGFW) bytes transferred per session for each source zone over the last 30 days

## Variations

_(No variations are documented for this entry.)_
