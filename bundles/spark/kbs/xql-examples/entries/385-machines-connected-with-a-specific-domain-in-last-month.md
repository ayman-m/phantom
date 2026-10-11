---
id: XQL-385-6ede6dcf
title: Machines Connected with a Specific Domain in Last Month
category: investigation
dataset: xdr_data
tags:
  - config
  - fields
  - filter
  - comp
  - xdr_data
  - source:dataset
---

# Machines Connected with a Specific Domain in Last Month

**Dataset**: `xdr_data`

```sql
config timeframe = 30d | dataset = xdr_data
| fields action_local_ip, action_remote_ip, agent_hostname , action_external_hostname
| filter action_external_hostname contains $domain
| comp values(agent_hostname) as local_hosts, values(action_local_ip) as local_ips, values(action_remote_ip) as remote_ips by action_external_hostname
| fields local_hosts , local_ips , remote_ips , action_external_hostname
```

## When to use

Searches the given domain across all the normalized data sources over the last month, and lists the related machines that were communicating with this domain

## Variations

_(No variations are documented for this entry.)_
