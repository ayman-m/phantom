---
id: XQL-832-fecfe92f
title: Incidents by MITRE tactic (30d) — array-expanded
category: investigation
dataset: incidents
tags:
  - filter
  - arrayexpand
  - comp
  - sort
  - limit
  - incidents
  - mitre
---

# Incidents by MITRE tactic (30d) — array-expanded

**Dataset**: `incidents`

```sql
config timeframe = 30d
| dataset = incidents
| filter mitre_tactics_id_and_name != null
| arrayexpand mitre_tactics_id_and_name
| comp count() as cnt by mitre_tactics_id_and_name
| sort desc cnt
| limit 10
```

## When to use

MITRE tactic distribution at the incident level.  is an array — arrayexpand to enable aggregation.

## Variations

_(No variations are documented for this entry.)_
