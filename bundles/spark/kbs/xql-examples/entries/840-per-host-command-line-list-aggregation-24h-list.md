---
id: XQL-840-1e83b7cc
title: Per-host command-line list aggregation (24h, list)
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - alter
  - fields
  - sort
  - limit
  - xdr_data
  - process
  - list
---

# Per-host command-line list aggregation (24h, list)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START and action_process_image_command_line != null
| comp list(action_process_image_command_line) as commands by agent_hostname
| alter command_count = array_length(commands)
| filter command_count >= 3
| fields agent_hostname, command_count
| sort desc command_count
| limit 10
```

## When to use

Per-host command-line collection via `list()` aggregation. Unlike `values()` (which deduplicates), `list()` keeps duplicates. Useful for forensic per-host command timelines.

## Variations

_(No variations are documented for this entry.)_
