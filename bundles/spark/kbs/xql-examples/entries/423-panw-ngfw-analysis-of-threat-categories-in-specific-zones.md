---
id: XQL-423-90ce4be4
title: PANW NGFW | Analysis of Threat Categories in Specific Zones
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - comp
  - sort
  - panw_ngfw_threat_raw
  - source:dataset
---

# PANW NGFW | Analysis of Threat Categories in Specific Zones

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| comp count() as threat_count by from_zone, to_zone, threat_category
| sort desc threat_count
```

## When to use

Categorizes Next-Generation-Firewall (NGFW) threats based on the source and destination zones

## Variations

_(No variations are documented for this entry.)_
