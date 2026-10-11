---
id: XQL-397-8f54931e
title: PANW NGFW | Average Session Duration per Application
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - config
  - comp
  - sort
  - panw_ngfw_traffic_raw
  - source:dataset
---

# PANW NGFW | Average Session Duration per Application

**Dataset**: `panw_ngfw_traffic_raw`

```sql
config timeframe = 7d
| dataset = panw_ngfw_traffic_raw
| comp avg(total_time_elapsed) as avg_duration by app
| sort desc avg_duration
```

## When to use

Calculates the average session duration for each Next-Generation-Firewall (NGFW) application over the last 7 days

## Variations

_(No variations are documented for this entry.)_
