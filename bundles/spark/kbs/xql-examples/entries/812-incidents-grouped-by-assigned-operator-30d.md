---
id: XQL-812-691e10de
title: Incidents grouped by assigned operator (30d)
category: investigation
dataset: incidents
tags:
  - filter
  - comp
  - sort
  - limit
  - incidents
---

# Incidents grouped by assigned operator (30d)

**Dataset**: `incidents`

```sql
config timeframe = 30d
| dataset = incidents
| filter assigned_user != null
| comp count() as cnt by assigned_user, status
| sort desc cnt
| limit 10
```

## When to use

Per-operator workload distribution. Field is `assigned_user` in this tenant (not `assigned_user_pretty_name`).

## Variations

_(No variations are documented for this entry.)_
