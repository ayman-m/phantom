---
id: XQL-736-621881cd
title: Distinct users per host (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - sort
  - limit
  - xdr_data
  - user
---

# Distinct users per host (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter actor_effective_username != null
| comp count_distinct(actor_effective_username) as unique_users, values(actor_effective_username) as users by agent_hostname
| sort desc unique_users
| limit 10
```

## When to use

How many distinct users were active per host? `count_distinct` + `values()` together give both the count and the list. Useful for finding shared-account hosts or atypical user activity.

## Variations

_(No variations are documented for this entry.)_
