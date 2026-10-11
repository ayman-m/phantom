---
id: XQL-408-94a063c2
title: PANW NGFW | Top 10 Specific Destination Zones by Blocked Traffic
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

# PANW NGFW | Top 10 Specific Destination Zones by Blocked Traffic

**Dataset**: `panw_ngfw_traffic_raw`

```sql
config timeframe = 30d
| dataset = panw_ngfw_traffic_raw
| filter action = "deny" and to_zone in ($to_zone)
| comp count() as blocked_count by to_zone
| sort desc blocked_count
| limit 10
```

## When to use

Identifies the top ten Next-Generation-Firewall (NGFW) destination zones that experienced the most blocked traffic over the last 30 days, filtering by specific destination zones

## Variations

_(No variations are documented for this entry.)_
