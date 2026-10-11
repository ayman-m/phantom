---
id: XQL-795-b6656f7a
title: Alerts by MITRE tactic + technique (30d)
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

# Alerts by MITRE tactic + technique (30d)

**Dataset**: `alerts`

```sql
config timeframe = 30d
| dataset = alerts
| filter mitre_attack_tactic != null
| comp count() as cnt by mitre_attack_tactic, mitre_attack_technique
| sort desc cnt
| limit 10
```

## When to use

Per-alert MITRE ATT&CK mapping using the live tenant's `mitre_attack_tactic` + `mitre_attack_technique` fields. Surfaces the tactic-coverage shape — which techniques fire most.

## Variations

_(No variations are documented for this entry.)_
