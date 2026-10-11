---
id: XQL-217-fc34282c
title: Children of Office processes that made more than 5 connections and wrote a binary to disk
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - comp
  - sort
  - join
  - dedup
  - xdr_data
  - source:dataset
---

# Children of Office processes that made more than 5 connections and wrote a binary to disk

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.NETWORK and lowercase(causality_actor_process_image_name) in ("winword.exe", "excel.exe", "powerpnt.exe") and causality_actor_process_image_name != actor_process_image_name // Filtering for cases where the CGO is an office process and is not doing the network connections on its own
 | fields agent_hostname as host_name, causality_actor_process_image_path as CGO_Path, causality_actor_process_command_line as CGO_CMD, causality_actor_primary_username as Username, actor_process_image_path as child_path, actor_process_command_line as child_cmd, actor_process_os_pid as child_pid, actor_process_image_sha256 as child_sha256, event_id, actor_process_instance_id as instance_id, agent_id, actor_process_execution_time as start_date // Selecting notable fields
 | comp count(event_id) as Counter by host_name, CGO_Path, CGO_CMD, Username, child_path, child_cmd, child_pid, child_sha256, instance_id, agent_id, start_date // Counting how many connections were done by the child process
 | filter Counter >= 5 // Filtering for more than 5 connections
 | sort desc Counter // Sorting in descending order
 |join (dataset = xdr_data | filter event_type = ENUM.FILE and (event_sub_type = ENUM.FILE_CREATE_NEW or event_sub_type = ENUM.FILE_WRITE) and lowercase(action_file_extension) in ("exe","dll","sys") | fields actor_process_instance_id as instance_id, agent_id, action_file_path) as file instance_id = file.instance_id and agent_id = file.agent_id // Joining for file create or write events of binary files by the same process (by the unique instance ID and agent id)
 | dedup start_date, host_name, CGO_Path, CGO_CMD, Username, child_path, child_cmd, child_pid, child_sha256, Counter, action_file_path by desc _time // Dedupping results since there could be multiple writes to the same file
 | fields start_date, host_name, CGO_Path, CGO_CMD, Username, child_path, child_cmd, child_pid, child_sha256, Counter, action_file_path as File_Path // Showing fields of interest
```

## When to use

Display processes spawned by an office process (not necessarily a direct child; could be anywhere on the chain of execution under the Office process) which made more than 5 connections, joined with file activity where the same process is also writing a binary to disk, using network connections and file activity

## Variations

_(No variations are documented for this entry.)_
