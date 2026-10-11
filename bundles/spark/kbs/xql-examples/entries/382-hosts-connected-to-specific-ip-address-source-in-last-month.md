---
id: XQL-382-6a04fad3
title: Hosts Connected to Specific IP Address/Source in Last Month
category: investigation
dataset: network_story
tags:
  - config
  - preset
  - filter
  - comp
  - sort
  - fields
  - network_story
  - source:preset
---

# Hosts Connected to Specific IP Address/Source in Last Month

**Dataset**: `network_story`

```sql
config timeframe = 30d | preset = network_story
| filter action_local_ip = $ip or action_remote_ip = $ip or actor_remote_ip = $ip or agent_ip_addresses contains $ip
| comp count() as connections, values(action_local_ip ) as source , values(action_remote_ip) as `target` by action_local_ip ,action_remote_ip
| sort desc connections
| fields source , `target` , connections
```

## When to use

Lists all the hosts that communicated with an IP address across all the normalized data sources in the last month

## Variations

_(No variations are documented for this entry.)_
