---
id: XQL-210-1c7dec6e
title: Processes running with double extensions
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
---

# Processes running with double extensions

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 |filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START and action_process_image_name ~= ".*?\.(?:pdf|docx|pptx|bat|mp3|xlsx|avi|mp4|jpg)\.exe" // Filtering for process start events and where the process name contains a regex pattern matching common double extensions seen in the wild
 | fields action_process_image_path as Process_Path, action_process_image_command_line as Process_CMD, action_process_os_pid as Process_PID, actor_process_image_path as Parent_Process, actor_process_command_line as Parent_CMD // Selecting some relevant fields
```

## When to use

Display all processes running with commonly seen double extensions

## Variations

_(No variations are documented for this entry.)_
