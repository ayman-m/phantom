---
id: XQL-411-fa161210
title: PANW NGFW | Top 10 Threat Categories Detected
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - comp
  - sort
  - limit
  - panw_ngfw_threat_raw
  - source:dataset
---

# PANW NGFW | Top 10 Threat Categories Detected

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| comp count() as threat_count by threat_category
| sort desc threat_count
| limit 10
```

## When to use

Identifies the top ten Next-Generation-Firewall (NGFW) threat categories detected by the firewall to help determine the most frequent types of threats faced by the network

## Variations

_(No variations are documented for this entry.)_
