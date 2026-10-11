---
id: XQL-216-f7a61550
title: Children of Office Processes that made more than 5 connections
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

# Children of Office Processes that made more than 5 connections

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.NETWORK and lowercase(causality_actor_process_image_name) in ("winword.exe", "excel.exe", "powerpnt.exe") and causality_actor_process_image_name != actor_process_image_name // Filtering for cases where the CGO is an office process and is not doing the network connections on its own
 | fields agent_hostname as host_name, causality_actor_process_image_path as CGO_Path, causality_actor_process_command_line as CGO_CMD, causality_actor_primary_username as Username, actor_process_image_path as child_path, actor_process_command_line as child_cmd, actor_process_os_pid as child_pid, actor_process_image_sha256 as child_sha256, actor_process_execution_time as start_date, event_id // Selecting notable fields
 | comp count(event_id) as Counter by host_name, CGO_Path, CGO_CMD, Username, child_path, child_cmd, child_pid, child_sha256, start_date // Counting how many connections were done by the child process
 | filter Counter >= 5 // Filtering for more than 5 connections
 | sort desc Counter // Sorting in descending order
 | fields start_date, host_name, CGO_Path, CGO_CMD, Username, child_path, child_cmd, child_pid, child_sha256, Counter // Showing fields of interest
```

## When to use

This query joins network connections with file activity to display processes that were spawned by an office process (not necessarily a direct child, could be anywhere in the chain of execution under office) that made more than 5 connections

## Variations

_(No variations are documented for this entry.)_
