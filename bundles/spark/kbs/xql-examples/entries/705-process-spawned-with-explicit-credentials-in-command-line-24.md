---
id: XQL-705-5fd60291
title: Process spawned with explicit credentials in command line (24h)
category: detection
dataset: xdr_data
tags:
  - filter
  - fields
  - limit
  - xdr_data
  - process
  - credentials
---

# Process spawned with explicit credentials in command line (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| filter action_process_image_command_line ~= "(?i)(/user:|-user |-u \S+ -p \S+|password=|passwd=)"
| fields _time, agent_hostname, actor_effective_username, action_process_image_name, action_process_image_command_line
| limit 10
```

## When to use

Processes with credentials hardcoded in command line — often indicates poor secret-hygiene or active attack (psexec, runas variants). The regex matches Windows-style credential flags.

## Variations

_(No variations are documented for this entry.)_
