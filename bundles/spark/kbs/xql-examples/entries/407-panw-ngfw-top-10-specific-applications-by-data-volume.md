---
id: XQL-407-c4f34ed6
title: PANW NGFW | Top 10 Specific Applications by Data Volume
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - config
  - filter
  - comp
  - sort
  - limit
  - panw_ngfw_traffic_raw
  - source:dataset
---

# PANW NGFW | Top 10 Specific Applications by Data Volume

**Dataset**: `panw_ngfw_traffic_raw`

```sql
config timeframe = 7d
| dataset = panw_ngfw_traffic_raw
| filter app in ($application)
| comp sum(bytes_total) as total_bytes by app
| sort desc total_bytes
| limit 10
```

## When to use

Identifies the top ten Next-Generation-Firewall (NGFW) applications generating the most network traffic (data volume) over the last 7 days, filtering by specific applications

## Variations

_(No variations are documented for this entry.)_
