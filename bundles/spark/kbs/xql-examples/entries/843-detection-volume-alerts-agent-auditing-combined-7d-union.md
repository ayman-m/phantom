---
id: XQL-843-9c340c02
title: Detection volume — alerts + agent_auditing combined (7d, union)
category: investigation
dataset: alerts
tags:
  - filter
  - comp
  - alter
  - union
  - sort
  - limit
  - alerts
  - agent_auditing
---

# Detection volume — alerts + agent_auditing combined (7d, union)

**Dataset**: `alerts`

```sql
config timeframe = 7d
| dataset = alerts
| comp count() as cnt by severity
| alter source = "alerts"
| union (dataset = agent_auditing | comp count() as cnt by agent_auditing_subtype | alter severity = agent_auditing_subtype, source = "agent_auditing" | fields severity, cnt, source)
| sort desc cnt
| limit 10
```

## When to use

Combines aggregated counts from two datasets (alerts + agent_auditing) into one unified view tagged with source. Demonstrates UNION with sub-query syntax + field projection per branch.

## Variations

_(No variations are documented for this entry.)_
