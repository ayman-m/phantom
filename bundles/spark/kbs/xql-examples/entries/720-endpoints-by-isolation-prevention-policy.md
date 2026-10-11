---
id: XQL-720-b7000465
title: Endpoints by isolation + prevention policy
category: investigation
dataset: endpoints
tags:
  - comp
  - sort
  - limit
  - endpoints
---

# Endpoints by isolation + prevention policy

**Dataset**: `endpoints`

```sql
dataset = endpoints
| comp count() as cnt by endpoint_isolated, assigned_prevention_policy
| sort desc cnt
| limit 10
```

## When to use

Reports the distribution of endpoint protection policies + isolation status across the fleet. Helps identify hosts running non-default policies or in isolation mode.

## Variations

_(No variations are documented for this entry.)_
