---
id: XQL-422-b71ee630
title: PANW NGFW | Threats Targeting Specific Users
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - filter
  - comp
  - sort
  - limit
  - panw_ngfw_threat_raw
  - source:dataset
---

# PANW NGFW | Threats Targeting Specific Users

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| filter source_user in ($source_user)
| comp count() as threat_count by source_user
| sort desc threat_count
| limit 10
```

## When to use

Identifies the top ten Next-Generation-Firewall (NGFW) threats that target specific users by filtering the logs for user-based threats

## Variations

_(No variations are documented for this entry.)_
