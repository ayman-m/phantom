---
id: XQL-703-d05f928f
title: PowerShell with encoded command flag (24h, T1059.001)
category: detection
dataset: xdr_data
tags:
  - filter
  - fields
  - limit
  - xdr_data
  - process
  - powershell
  - T1059.001
---

# PowerShell with encoded command flag (24h, T1059.001)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| filter lowercase(action_process_image_name) = "powershell.exe"
| filter lowercase(action_process_image_command_line) contains "-enc" or lowercase(action_process_image_command_line) contains "-encodedcommand"
| fields _time, agent_hostname, actor_process_image_name, action_process_image_command_line
| limit 10
```

## When to use

PowerShell with -EncodedCommand / -enc is a classic obfuscation technique (MITRE T1059.001). Flag any execution + return the host + parent + full command line for triage.

## Variations

_(No variations are documented for this entry.)_
