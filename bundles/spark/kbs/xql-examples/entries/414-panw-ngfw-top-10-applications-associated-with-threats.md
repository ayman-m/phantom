---
id: XQL-414-0827ac9d
title: PANW NGFW | Top 10 Applications Associated with Threats
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - comp
  - sort
  - limit
  - panw_ngfw_threat_raw
  - source:dataset
---

# PANW NGFW | Top 10 Applications Associated with Threats

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| comp count() as threat_count by app
| sort desc threat_count
| limit 10
```

## When to use

Identifies the top ten Next-Generation-Firewall (NGFW) applications that are most frequently associated with detected threats

## Variations

_(No variations are documented for this entry.)_
