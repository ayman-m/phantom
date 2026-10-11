---
id: XQL-749-a856ccc0
title: Case-insensitive process match using config (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - sort
  - limit
  - xdr_data
  - process
  - config
---

# Case-insensitive process match using config (24h)

**Dataset**: `xdr_data`

```sql
config case_sensitive = false timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| filter action_process_image_name = "powershell.exe"
| fields _time, agent_hostname, action_process_image_name, action_process_image_command_line
| sort desc _time
| limit 10
```

## When to use

Uses `config case_sensitive = false` so the equality match is case-insensitive without needing `lowercase()` wrapping. Useful for cleaner queries on case-mixed Windows paths.

## Variations

_(No variations are documented for this entry.)_
