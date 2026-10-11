---
id: XQL-801-20de0616
title: Alerts with category + tactic (30d)
category: investigation
dataset: alerts
tags:
  - filter
  - comp
  - sort
  - limit
  - alerts
  - mitre
---

# Alerts with category + tactic (30d)

**Dataset**: `alerts`

```sql
config timeframe = 30d
| dataset = alerts
| filter category != null
| comp count() as cnt by category, mitre_attack_tactic
| sort desc cnt
| limit 10
```

## When to use

Cross-tab of alert category vs MITRE tactic. Reveals how categories distribute across tactics.

## Variations

_(No variations are documented for this entry.)_
