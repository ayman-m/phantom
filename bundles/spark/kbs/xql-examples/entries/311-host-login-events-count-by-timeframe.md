---
id: XQL-311-cf4b442c
title: Host Login Events Count by Timeframe
category: investigation
dataset: xdr_login_events
tags:
  - preset
  - filter
  - comp
  - sort
  - fields
  - xdr_login_events
  - source:preset
---

# Host Login Events Count by Timeframe

**Dataset**: `xdr_login_events`

```sql
preset = xdr_login_events
| filter array_length(assigned_privileges ) > 0 or elevated_token != null
| filter agent_hostname in($host)
| comp count() as login_count by agent_hostname, agent_ip_addresses, agent_os_type
| sort desc login_count
| fields agent_hostname, agent_ip_addresses, agent_os_type, login_count
```

## When to use

Counts log in events per host within a defined timeframe to help monitor authentication activity and identify potential security concerns related to abnormal log in behaviors

## Variations

_(No variations are documented for this entry.)_
