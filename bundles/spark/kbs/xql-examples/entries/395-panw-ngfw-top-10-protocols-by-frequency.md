---
id: XQL-395-03042904
title: PANW NGFW | Top 10 Protocols by Frequency
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

# PANW NGFW | Top 10 Protocols by Frequency

**Dataset**: `panw_ngfw_traffic_raw`

```sql
config timeframe = 7d
| dataset = panw_ngfw_traffic_raw
| comp count() as protocol_count by protocol
| sort desc protocol_count
| limit 10
```

## When to use

Identifies the top ten Next-Generation-Firewall (NGFW) used protocols in the network traffic over the last 7 days

## Variations

_(No variations are documented for this entry.)_
