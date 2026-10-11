---
id: XQL-191-9d551374
title: Unique Injections by unsigned Process
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - dedup
  - xdr_data
  - source:dataset
---

# Unique Injections by unsigned Process

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.INJECTION and actor_process_signature_status != ENUM.SIGNED // Filtering by injection events and by acting process that is unsigned
 | fields actor_process_image_path as Source_Process_Path, actor_process_command_line as Source_Process_CMD, action_remote_process_image_path as Target_Process_Path, action_remote_process_image_command_line as Target_Process_CMD // Selecting the fields needed like the source process and cmd and the target process and cmd
 | dedup Target_Process_CMD,Source_Process_Path,Source_Process_CMD,Target_Process_Path by asc _time // Using dedup function to only get the first occurrence of each tuple by time
```

## When to use

Display an unsigned process injecting code to a target process. Displays one result per pair

## Variations

_(No variations are documented for this entry.)_
