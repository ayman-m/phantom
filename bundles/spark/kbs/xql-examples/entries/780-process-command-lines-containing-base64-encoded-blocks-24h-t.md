---
id: XQL-780-ad078d3a
title: Process command lines containing base64-encoded blocks (24h, T1027)
category: detection
dataset: xdr_data
tags:
  - filter
  - fields
  - sort
  - limit
  - xdr_data
  - process
  - T1027
  - regex
---

# Process command lines containing base64-encoded blocks (24h, T1027)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| filter action_process_image_command_line ~= "[A-Za-z0-9+/]{50,}={0,2}"
| fields _time, agent_hostname, action_process_image_name, action_process_image_command_line
| sort desc _time
| limit 10
```

## When to use

Command lines containing long base64-looking blocks (MITRE T1027 — Obfuscated Files or Information). The regex matches 50+ base64 chars optionally padded with =.

## Variations

_(No variations are documented for this entry.)_
