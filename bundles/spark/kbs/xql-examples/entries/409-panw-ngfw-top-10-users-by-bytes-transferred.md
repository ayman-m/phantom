---
id: XQL-409-9fa0a89c
title: PANW NGFW | Top 10 Users by Bytes Transferred 
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

# PANW NGFW | Top 10 Users by Bytes Transferred 

**Dataset**: `panw_ngfw_traffic_raw`

```sql
config timeframe = 30d
| dataset = panw_ngfw_traffic_raw
| filter source_user in ($source_user)
| comp sum(bytes_total) as total_bytes by source_user
| sort desc total_bytes
| limit 10
```

## When to use

Identifies the top ten Next-Generation-Firewall (NGFW) users responsible for the highest volume of data transfer in the last 30 days, filtering by specific users

## Variations

_(No variations are documented for this entry.)_
