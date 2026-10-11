---
id: XQL-823-8ba4206d
title: Alerts by MITRE tactic (30d) — scalar field
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

# Alerts by MITRE tactic (30d) — scalar field

**Dataset**: `alerts`

```sql
config timeframe = 30d
| dataset = alerts
| filter mitre_attack_tactic != null
| comp count() as cnt by mitre_attack_tactic
| sort desc cnt
| limit 10
```

## When to use

Per-tactic alert distribution. `mitre_attack_tactic` is a scalar string in this tenant — direct aggregation works, no arrayexpand needed.

## Variations

_(No variations are documented for this entry.)_
