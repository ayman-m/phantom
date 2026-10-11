---
id: XQL-417-f71c8570
title: PANW NGFW | Top 10 Threat IDs Detected
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - comp
  - sort
  - limit
  - panw_ngfw_threat_raw
  - source:dataset
---

# PANW NGFW | Top 10 Threat IDs Detected

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| comp count() as threat_count by threat_id
| sort desc threat_count
| limit 10
```

## When to use

Identifies the top ten Next-Generation-Firewall (NGFW) threat IDs detected on the network

## Variations

_(No variations are documented for this entry.)_
