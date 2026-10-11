---
id: XQL-209-f52fd6f1
title: All executions of JAR files by javaw.exe
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
---

# All executions of JAR files by javaw.exe

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset 
 | filter action_process_image_name = "javaw.exe" and action_process_image_command_line contains ".jar" // Filtering by process name is javaw.exe and command line contains .jar
 | fields action_process_image_path as Process_Path, action_process_image_command_line as Process_CMD, actor_process_image_path as Parent_Path, actor_process_command_line as Parent_CMD // Selecting all the relevant fields
```

## When to use

Display all cases where javaw.exe was used to run a jar file

## Variations

_(No variations are documented for this entry.)_
