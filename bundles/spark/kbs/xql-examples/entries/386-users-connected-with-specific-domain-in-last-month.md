---
id: XQL-386-7d1c4e9e
title: Users Connected with Specific Domain in Last Month
category: investigation
dataset: xdr_data
tags:
  - config
  - fields
  - filter
  - dedup
  - xdr_data
  - source:dataset
---

# Users Connected with Specific Domain in Last Month

**Dataset**: `xdr_data`

```sql
config timeframe = 30d | dataset = xdr_data
| fields actor_effective_username , action_remote_ip , action_external_hostname
| filter action_external_hostname contains $domain
| filter actor_effective_username != null
| dedup actor_effective_username
| fields actor_effective_username , action_remote_ip , action_external_hostname
```

## When to use

Searches the given domain across all the normalized data sources over the last month, and lists the related user details

## Variations

_(No variations are documented for this entry.)_
