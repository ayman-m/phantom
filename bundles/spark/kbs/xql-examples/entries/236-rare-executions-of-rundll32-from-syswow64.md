---
id: XQL-236-08a01e7d
title: Rare executions of Rundll32 from Syswow64
category: investigation
dataset: xdr_data
tags:
  - filter
  - alter
  - fields
  - comp
  - sort
  - xdr_data
  - source:dataset
---

# Rare executions of Rundll32 from Syswow64

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
| filter lowercase(action_process_image_name) = "rundll32.exe" and lowercase(action_process_image_path) contains "syswow64" // Filtering for cases where rundll32.exe is running from syswow64
| alter process_cmd = if(lowercase(action_process_image_command_line) contains "c:\users", replex(lowercase(action_process_image_command_line), "c:\\users\\[a-zA-Z0-9.]*", "c:\\users\\USERNAME"), action_process_image_command_line) // Running an alter command to make sure the functions later ignore differences in user paths
| fields action_process_image_path as process_path, process_cmd, actor_process_image_path as parent_path, actor_process_command_line as parent_cmd, event_id, causality_actor_process_image_path as cgo_path, causality_actor_process_command_line as cgo_cmd // Selecting relevant fiends
| comp count(event_id) as counter by process_path, process_cmd, parent_path, parent_cmd, cgo_path, cgo_cmd // Counting how many times each combination appeared 
| filter counter <= 5 // Showing just cases that happened 5 times or less
| sort desc counter // Sorting in desc by counter
```

## When to use

Displays rare executions of Rundll32 being executed from syswow64

## Variations

_(No variations are documented for this entry.)_
