---
id: XQL-378-30cdb3e3
title: Usual Ratio of Failed vs Successful Logins for Specific Users in Last Month
category: investigation
dataset: authentication_story
tags:
  - config
  - preset
  - filter
  - bin
  - alter
  - comp
  - sort
  - fields
  - authentication_story
  - source:preset
---

# Usual Ratio of Failed vs Successful Logins for Specific Users in Last Month

**Dataset**: `authentication_story`

```sql
config timeframe = 30d
| preset = authentication_story
| filter auth_identity contains $user
| bin _time span = 24h
| alter success_boolean = if(auth_outcome = "SUCCESS", 1 , 0)
| alter failure_boolean = if(auth_outcome = "FAILURE", 1 , 0)
| filter auth_outcome != null and auth_identity != null
| comp count() as total_authentication_events, sum(success_boolean ) as success_count, values(auth_outcome_reason ) as auth_outcome_reason, values(associated_products ) as products , values(action_country ) as source_country, values(auth_outcome) as outcome, sum(failure_boolean) as failure_count  by  auth_identity  , auth_client , auth_target
| alter success_ratio = divide(success_count , total_authentication_events )
| sort asc success_ratio
| fields auth_identity, success_ratio , *
```

## When to use

Lists the daily average number of authentication events performed in the last month by a specific user

## Variations

_(No variations are documented for this entry.)_
