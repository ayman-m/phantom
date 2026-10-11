---
id: XQL-707-f7462c8c
title: Long process command lines — possible obfuscation (24h)
category: detection
dataset: xdr_data
tags:
  - filter
  - alter
  - fields
  - sort
  - limit
  - xdr_data
  - process
---

# Long process command lines — possible obfuscation (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| alter cmd_len = len(action_process_image_command_line)
| filter cmd_len > 500
| fields _time, agent_hostname, action_process_image_name, cmd_len, action_process_image_command_line
| sort desc cmd_len
| limit 10
```

## When to use

Excessively long command lines (>500 chars) often indicate obfuscated PowerShell, base64 payloads, or other evasion techniques. `len()` builds the length column for sorting.

## Variations

_(No variations are documented for this entry.)_
