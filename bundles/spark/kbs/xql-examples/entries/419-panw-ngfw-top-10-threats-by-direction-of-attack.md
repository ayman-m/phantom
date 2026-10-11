---
id: XQL-419-e27273a8
title: PANW NGFW | Top 10 Threats by Direction of Attack
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - comp
  - sort
  - limit
  - panw_ngfw_threat_raw
  - source:dataset
---

# PANW NGFW | Top 10 Threats by Direction of Attack

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| comp count() as threat_count by direction_of_attack
| sort desc threat_count
| limit 10
```

## When to use

Categorizes the top ten Next-Generation-Firewall (NGFW) threats based on their direction of attack

## Variations

_(No variations are documented for this entry.)_
