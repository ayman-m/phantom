---
id: XQL-396-3c6a6bee
title: PANW NGFW | Top 10 Users by Data Transfer
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

# PANW NGFW | Top 10 Users by Data Transfer

**Dataset**: `panw_ngfw_traffic_raw`

```sql
config timeframe = 30d
| dataset = panw_ngfw_traffic_raw
| comp sum(bytes_total) as total_bytes by source_user
| sort desc total_bytes
| limit 10
```

## When to use

Identifies the top ten Next-Generation-Firewall (NGFW) users responsible for the highest volume of data transfer in the last 30 days

## Variations

_(No variations are documented for this entry.)_
