---
id: XQL-830-9b5f1115
title: Incidents by alert-source (30d) — array-expanded
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

# Incidents by alert-source (30d) — array-expanded

**Dataset**: `incidents`

```sql
config timeframe = 30d
| dataset = incidents
| filter alert_sources != null
| arrayexpand alert_sources
| comp count() as cnt by alert_sources
| sort desc cnt
| limit 10
```

## When to use

Per-detection-source incident distribution. `alert_sources` array from constituent alerts.

## Variations

_(No variations are documented for this entry.)_
