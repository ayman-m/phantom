---
id: XQL-391-d95243c1
title: PANW NGFW |  Allowed vs. Denied Traffic Distribution
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - config
  - comp
  - sort
  - panw_ngfw_traffic_raw
  - source:dataset
---

# PANW NGFW |  Allowed vs. Denied Traffic Distribution

**Dataset**: `panw_ngfw_traffic_raw`

```sql
config timeframe = 7d
| dataset = panw_ngfw_traffic_raw
| comp count() as action_count by action
| sort desc action_count
```

## When to use

Calculates the distribution of Next-Generation-Firewall (NGFW) allowed vs. denied traffic in the last 7 days by analyzing firewall actions

## Variations

_(No variations are documented for this entry.)_
