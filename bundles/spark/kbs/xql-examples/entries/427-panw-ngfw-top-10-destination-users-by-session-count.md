---
id: XQL-427-3f750329
title: PANW NGFW | Top 10 Destination Users by Session Count
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - config
  - comp
  - sort
  - limit
  - panw_ngfw_traffic_raw
  - source:dataset
---

# PANW NGFW | Top 10 Destination Users by Session Count

**Dataset**: `panw_ngfw_traffic_raw`

```sql
config timeframe = 30d
| dataset = panw_ngfw_traffic_raw
| comp count() as session_count by dest_user
| sort desc session_count
| limit 10
```

## When to use

Identifies the top ten Next-Generation-Firewall (NGFW) destination users based on the number of network sessions over the past 30 days

## Variations

_(No variations are documented for this entry.)_
