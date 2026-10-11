---
id: XQL-313-f4258ace
title: Policy Assignment and Endpoint Distribution
category: investigation
dataset: endpoints
tags:
  - fields
  - filter
  - comp
  - endpoints
  - source:dataset
---

# Policy Assignment and Endpoint Distribution

**Dataset**: `endpoints`

```sql
dataset = endpoints
| fields endpoint_name, assigned_prevention_policy, assigned_extensions_policy
| filter assigned_prevention_policy in($policy)
| comp count_distinct(endpoint_name) as PreventionPolicyCount by assigned_prevention_policy
```

## When to use

Details the various security policies in place within the environment and how many endpoints are assigned to each policy to ensure comprehensive coverage across all devices

## Variations

_(No variations are documented for this entry.)_
