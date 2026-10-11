---
id: XQL-706-df57f8b6
title: Recent process executions on specific host (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - sort
  - limit
  - xdr_data
  - process
---

# Recent process executions on specific host (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| filter lowercase(agent_hostname) = "win-host-01"
| fields _time, agent_hostname, actor_process_image_name, action_process_image_name, action_process_image_command_line, actor_effective_username
| sort desc _time
| limit 10
```

## When to use

Investigation pivot — given a specific host of interest, return the most recent process-start events with parent/child + command line + initiating user. Replace 'win-host-01' with the target host.

## Variations

_(No variations are documented for this entry.)_
