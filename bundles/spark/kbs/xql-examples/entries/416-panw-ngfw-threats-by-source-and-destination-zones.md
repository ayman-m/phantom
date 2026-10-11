---
id: XQL-416-66bb8912
title: PANW NGFW | Threats by Source and Destination Zones
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - comp
  - sort
  - panw_ngfw_threat_raw
  - source:dataset
---

# PANW NGFW | Threats by Source and Destination Zones

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| comp count() as threat_count by from_zone, to_zone
| sort desc threat_count
```

## When to use

Calculates which Next-Generation-Firewall (NGFW) network zones most frequently involve the detection of threats

## Variations

_(No variations are documented for this entry.)_
