---
id: XQL-400-317441b1
title: PANW NGFW | Top 10 Destination IPs by Data Volume
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

# PANW NGFW | Top 10 Destination IPs by Data Volume

**Dataset**: `panw_ngfw_traffic_raw`

```sql
config timeframe = 30d
| dataset = panw_ngfw_traffic_raw
| comp sum(bytes_received) as total_bytes_received by dest_ip
| sort desc total_bytes_received
| limit 10
```

## When to use

Identifies the top 10 Next-Generation-Firewall (NGFW)  destination IPs that received the most data in the last 30 days

## Variations

_(No variations are documented for this entry.)_
