---
id: XQL-387-fe30cd59
title: Prevalence of Specific Domain "communication with" in this Organization in Last Month
category: investigation
dataset: xdr_data
tags:
  - config
  - filter
  - fields
  - bin
  - comp
  - alter
  - xdr_data
  - source:dataset
---

# Prevalence of Specific Domain "communication with" in this Organization in Last Month

**Dataset**: `xdr_data`

```sql
config timeframe = 30d
| dataset = xdr_data
| filter action_external_hostname contains $domain
| fields dst_action_external_hostname , action_external_hostname
| filter action_external_hostname != null
| bin _time span = 1d
| comp count() as c by action_external_hostname , _time
| comp avg(c) as average_per_day,list(c) as count_values, var(c) as variance, earliest(_time) as `earliest`, latest(_time) as `latest`,count_distinct(_time) as days_appeared_count  by action_external_hostname addrawdata = true
| alter stdev = pow(variance ,0.5)
```

## When to use

Details statistics on the communication with a given domain in the last month

## Variations

_(No variations are documented for this entry.)_
