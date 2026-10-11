---
id: XQL-398-e6b359c2
title: PANW NGFW | Top 10 Destination Ports by Bytes Sent
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

# PANW NGFW | Top 10 Destination Ports by Bytes Sent

**Dataset**: `panw_ngfw_traffic_raw`

```sql
config timeframe = 7d
| dataset = panw_ngfw_traffic_raw
| comp sum(bytes_sent) as total_bytes_sent by dest_port
| sort desc total_bytes_sent
| limit 10
```

## When to use

Identifies the top ten Next-Generation-Firewall (NGFW) destination ports that received the most data in the last 7 days

## Variations

_(No variations are documented for this entry.)_
