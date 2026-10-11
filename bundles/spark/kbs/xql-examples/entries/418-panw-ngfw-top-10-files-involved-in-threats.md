---
id: XQL-418-133a2460
title: PANW NGFW | Top 10 Files Involved in Threats
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - comp
  - sort
  - limit
  - panw_ngfw_threat_raw
  - source:dataset
---

# PANW NGFW | Top 10 Files Involved in Threats

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| comp count() as file_count by file_name
| sort desc file_count
| limit 10
```

## When to use

Identifies the top ten Next-Generation-Firewall (NGFW) files detected involved in threats

## Variations

_(No variations are documented for this entry.)_
