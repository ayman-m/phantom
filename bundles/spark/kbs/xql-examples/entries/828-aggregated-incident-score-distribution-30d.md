---
id: XQL-828-0a977d26
title: Aggregated incident score distribution (30d)
category: investigation
dataset: incidents
tags:
  - filter
  - comp
  - sort
  - limit
  - incidents
---

# Aggregated incident score distribution (30d)

**Dataset**: `incidents`

```sql
config timeframe = 30d
| dataset = incidents
| filter aggregated_score != null
| comp count() as cnt, avg(aggregated_score) as avg_score, max(aggregated_score) as max_score by severity
| sort desc max_score
| limit 10
```

## When to use

Per-severity incident score statistics (avg + max). aggregated_score is XSIAM's composite incident-risk score.

## Variations

_(No variations are documented for this entry.)_
