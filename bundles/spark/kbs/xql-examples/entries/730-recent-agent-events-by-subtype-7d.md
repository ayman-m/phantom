---
id: XQL-730-be66fa63
title: Recent agent events by subtype (7d)
category: investigation
dataset: agent_auditing
tags:
  - filter
  - comp
  - sort
  - limit
  - agent_auditing
---

# Recent agent events by subtype (7d)

**Dataset**: `agent_auditing`

```sql
config timeframe = 7d
| dataset = agent_auditing
| comp count() as cnt by agent_auditing_subtype
| sort desc cnt
| limit 10
```

## When to use

Agent self-audit event distribution — start/stop, policy applied, upgrade, error, etc. Useful for understanding agent fleet health.

## Variations

_(No variations are documented for this entry.)_
