---
id: XQL-232-0d5d0565
title: Mshta running an HTA file
category: investigation
dataset: xdr_process
tags:
  - preset
  - filter
  - fields
  - dedup
  - xdr_process
  - source:preset
---

# Mshta running an HTA file

**Dataset**: `xdr_process`

```sql
preset = xdr_process  // Using XDR process execution preset
| filter action_process_image_name  = "mshta.exe"  and action_process_image_command_line contains ".hta" // Filtering by process name is mshta.exe and an hta file is in the command line
| fields action_process_image_path as process_path, action_process_image_command_line as process_cmd, actor_process_image_name as parent_process, actor_process_command_line as parent_cmd // Selecting relevant fields
| dedup process_path, process_cmd, parent_process, parent_cmd by asc _time // Dedupping to only show the first time
```

## When to use

Displays cases where mshta.exe ran an hta file

## Variations

_(No variations are documented for this entry.)_
