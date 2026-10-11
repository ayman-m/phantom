---
id: XQL-404-286ac66b
title: PANW NGFW | Top 10 Source Locations by Data Volume
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

# PANW NGFW | Top 10 Source Locations by Data Volume

**Dataset**: `panw_ngfw_traffic_raw`

```sql
config timeframe = 30d
| dataset = panw_ngfw_traffic_raw
| comp sum(bytes_total) as total_bytes by source_location
| sort desc total_bytes
| limit 10
```

## When to use

Identifies the top ten Next-Generation-Firewall (NGFW) source locations that generated the most traffic in terms of bytes transferred in the last 30 days

## Variations

_(No variations are documented for this entry.)_
