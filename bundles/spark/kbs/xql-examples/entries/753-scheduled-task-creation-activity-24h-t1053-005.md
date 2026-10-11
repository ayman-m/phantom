---
id: XQL-753-59e30890
title: Scheduled-task creation activity (24h, T1053.005)
category: detection
dataset: xdr_data
tags:
  - filter
  - fields
  - sort
  - limit
  - xdr_data
  - process
  - T1053.005
---

# Scheduled-task creation activity (24h, T1053.005)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| filter lowercase(action_process_image_name) in ("schtasks.exe", "at.exe")
| filter lowercase(action_process_image_command_line) contains "/create"
| fields _time, agent_hostname, actor_effective_username, action_process_image_command_line
| sort desc _time
| limit 10
```

## When to use

Scheduled task creation — MITRE T1053.005. One of the most common persistence techniques. Captures schtasks /create + at command invocations.

## Variations

_(No variations are documented for this entry.)_
