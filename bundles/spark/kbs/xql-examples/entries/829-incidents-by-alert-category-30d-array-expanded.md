---
id: XQL-829-90fc902c
title: Incidents by alert-category (30d) — array-expanded
category: investigation
dataset: incidents
tags:
  - filter
  - arrayexpand
  - comp
  - sort
  - limit
  - incidents
---

# Incidents by alert-category (30d) — array-expanded

**Dataset**: `incidents`

```sql
config timeframe = 30d
| dataset = incidents
| filter alert_categories != null
| arrayexpand alert_categories
| comp count() as cnt by alert_categories
| sort desc cnt
| limit 10
```

## When to use

Per-alert-category incident distribution. `alert_categories` is an array of categories from the constituent alerts.

## Variations

_(No variations are documented for this entry.)_
