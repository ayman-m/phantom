---
id: XQL-406-bf55ec14
title: PANW NGFW | Average Packets per Session by Source User
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - config
  - comp
  - sort
  - panw_ngfw_traffic_raw
  - source:dataset
---

# PANW NGFW | Average Packets per Session by Source User

**Dataset**: `panw_ngfw_traffic_raw`

```sql
config timeframe = 30d
| dataset = panw_ngfw_traffic_raw
| comp avg(packets_total) as avg_packets_per_session by source_user
| sort desc avg_packets_per_session
```

## When to use

Calculates the average number of Next-Generation-Firewall (NGFW) packets per session for each source user in the last 30 days

## Variations

_(No variations are documented for this entry.)_
