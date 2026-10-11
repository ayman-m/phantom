---
id: XQL-410-54583e87
title: PANW NGFW | Top 10 Source-Destination Pairs by Session Count
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

# PANW NGFW | Top 10 Source-Destination Pairs by Session Count

**Dataset**: `panw_ngfw_traffic_raw`

```sql
config timeframe = 7d
| dataset = panw_ngfw_traffic_raw
| filter source_ip in ($source_ip) and dest_ip in ($dest_ip)
| comp count() as session_count by source_ip, dest_ip
| sort desc session_count
| limit 10
```

## When to use

Identifies the top ten Next-Generation-Firewall (NGFW) source-destination IP pairs with the highest number of network sessions in the last 7 days, filtering by specific source and destination IPs

## Variations

_(No variations are documented for this entry.)_
