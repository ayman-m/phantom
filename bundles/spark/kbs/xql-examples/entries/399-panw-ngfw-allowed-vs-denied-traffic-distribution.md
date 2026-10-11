---
id: XQL-399-c26913e4
title: PANW NGFW | Allowed vs. Denied Traffic Distribution
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - config
  - comp
  - sort
  - panw_ngfw_traffic_raw
  - source:dataset
---

# PANW NGFW | Allowed vs. Denied Traffic Distribution

**Dataset**: `panw_ngfw_traffic_raw`

```sql
config timeframe = 7d
| dataset = panw_ngfw_traffic_raw
| comp count() as action_count by action
| sort desc action_count
```

## When to use

Calculates the Next-Generation-Firewall (NGFW) distribution of allowed vs. denied traffic within the last 7 days, providing insight into the balance between traffic allowed through the firewall versus the traffic denied

## Variations

_(No variations are documented for this entry.)_
