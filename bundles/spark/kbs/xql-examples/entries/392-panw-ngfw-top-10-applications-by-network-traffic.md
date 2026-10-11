---
id: XQL-392-27fac3d2
title: PANW NGFW |  Top 10 Applications by Network Traffic
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

# PANW NGFW |  Top 10 Applications by Network Traffic

**Dataset**: `panw_ngfw_traffic_raw`

```sql
config timeframe = 7d
| dataset = panw_ngfw_traffic_raw
| comp sum(bytes_total) as total_bytes by app
| sort desc total_bytes
| limit 10
```

## When to use

Identifies the top ten Next-Generation-Firewall (NGFW) applications generating the most network traffic (data volume) over the last 7 days

## Variations

_(No variations are documented for this entry.)_
