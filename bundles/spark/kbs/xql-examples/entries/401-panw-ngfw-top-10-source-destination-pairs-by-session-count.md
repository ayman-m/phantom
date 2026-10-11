---
id: XQL-401-b0c396c6
title: PANW NGFW | Top 10 Source-Destination Pairs by Session Count
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

# PANW NGFW | Top 10 Source-Destination Pairs by Session Count

**Dataset**: `panw_ngfw_traffic_raw`

```sql
config timeframe = 7d
| dataset = panw_ngfw_traffic_raw
| comp count() as session_count by source_ip, dest_ip
| sort desc session_count
| limit 10
```

## When to use

Identifies the top ten Next-Generation-Firewall (NGFW) source-destination IP pairs with the highest number of network sessions in the last 7 days

## Variations

_(No variations are documented for this entry.)_
