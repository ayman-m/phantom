---
id: XQL-772-2d5d7d5b
title: Agent installations + upgrades (7d)
category: investigation
dataset: agent_auditing
tags:
  - filter
  - comp
  - sort
  - limit
  - agent_auditing
---

# Agent installations + upgrades (7d)

**Dataset**: `agent_auditing`

```sql
config timeframe = 7d
| dataset = agent_auditing
| filter agent_auditing_subtype in (ENUM.AGENT_AUDIT_INSTALL, ENUM.AGENT_AUDIT_UPGRADE)
| comp count() as cnt by endpoint_name, agent_auditing_subtype
| sort desc cnt
| limit 10
```

## When to use

Agent install + upgrade activity. Reveals rollout progress + endpoints that have had unusual lifecycle activity.

## Variations

_(No variations are documented for this entry.)_
