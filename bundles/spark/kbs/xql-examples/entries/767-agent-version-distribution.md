---
id: XQL-767-2ff8fb81
title: Agent version distribution
category: investigation
dataset: endpoints
tags:
  - comp
  - sort
  - limit
  - endpoints
---

# Agent version distribution

**Dataset**: `endpoints`

```sql
dataset = endpoints
| comp count() as cnt by agent_version, platform
| sort desc cnt
| limit 10
```

## When to use

Agent version landscape across the fleet. Useful for rollout-progress tracking + spotting outdated agents that need upgrading.

## Variations

_(No variations are documented for this entry.)_
