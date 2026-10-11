---
id: XQL-239-9c68518f
title: Rare processes started by Powershell
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - comp
  - sort
  - xdr_data
  - source:dataset
---

# Rare processes started by Powershell

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the XDR dataset
| filter event_type = ENUM.PROCESS  and event_sub_type = ENUM.PROCESS_START and lowercase(actor_process_image_name) = "powershell.exe" // Filtering for parent process is powershell.exe
| fields action_process_image_name as process_name, action_process_image_command_line as process_cmd, event_id // Getting the relevant fields
| comp count(event_id ) as counter by process_name , process_cmd  // Counting how many times each process was started by powershell with a specific command line
| filter counter <= 5 // Filtering for 5 or less cases of an execution
| sort desc counter // Sorting in desc order
```

## When to use

Displays rare executions of of processes by Powershell

## Variations

_(No variations are documented for this entry.)_
