---
id: XQL-420-3799effd
title: PANW NGFW | Top 10 Source Users Involved in Threats
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - comp
  - sort
  - limit
  - panw_ngfw_threat_raw
  - source:dataset
---

# PANW NGFW | Top 10 Source Users Involved in Threats

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| comp count() as threat_count by source_user
| sort desc threat_count
| limit 10
```

## When to use

Identifies the top ten Next-Generation-Firewall (NGFW)  source users associated with detected threats

## Variations

_(No variations are documented for this entry.)_
