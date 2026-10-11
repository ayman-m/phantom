---
id: XQL-393-a669696d
title: PANW NGFW | Top 10 Source IP Addresses by Session Count
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - comp
  - sort
  - limit
  - panw_ngfw_traffic_raw
  - source:dataset
---

# PANW NGFW | Top 10 Source IP Addresses by Session Count

**Dataset**: `panw_ngfw_traffic_raw`

```sql
dataset = panw_ngfw_traffic_raw
| comp count() as session_count by source_ip
| sort desc session_count
| limit 10
```

## When to use

Identifies the top ten Next-Generation-Firewall (NGFW) source IP addresses with the highest number of network sessions

## Variations

_(No variations are documented for this entry.)_
