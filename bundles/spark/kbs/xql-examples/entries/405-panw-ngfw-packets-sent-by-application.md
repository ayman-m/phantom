---
id: XQL-405-3b2edd56
title: PANW NGFW | Packets Sent by Application
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - config
  - comp
  - sort
  - panw_ngfw_traffic_raw
  - source:dataset
---

# PANW NGFW | Packets Sent by Application

**Dataset**: `panw_ngfw_traffic_raw`

```sql
config timeframe = 7d
| dataset = panw_ngfw_traffic_raw
| comp sum(packets_sent) as total_packets_sent by app
| sort desc total_packets_sent
```

## When to use

Lists the total number of Next-Generation-Firewall (NGFW) packets sent by each application over the last 7 days

## Variations

_(No variations are documented for this entry.)_
