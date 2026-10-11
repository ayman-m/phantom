---
id: XQL-848-61db6424
title: Process command-line backslash count (24h, string_count)
category: investigation
dataset: xdr_data
tags:
  - filter
  - alter
  - fields
  - sort
  - limit
  - xdr_data
  - process
  - string_count
---

# Process command-line backslash count (24h, string_count)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| filter action_process_image_command_line != null
| alter backslash_count = string_count(action_process_image_command_line, "\\\\")
| filter backslash_count > 5
| fields _time, agent_hostname, action_process_image_name, backslash_count, action_process_image_command_line
| sort desc backslash_count
| limit 10
```

## When to use

Surfaces command lines with many backslashes — often indicates deep file-path args or obfuscation. `string_count(field, substring)` returns the count.

## Variations

_(No variations are documented for this entry.)_
