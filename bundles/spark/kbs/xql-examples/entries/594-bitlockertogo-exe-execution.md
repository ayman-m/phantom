---
id: XQL-594-238a92f3
title: BitLockerTogo.EXE Execution
category: investigation
dataset: xdr_data
tags:
  - filter
  - alter
  - fields
  - xdr_data
  - source:dataset
  - Process
---

# BitLockerTogo.EXE Execution

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = 1 and event_sub_type = 1
| filter (action_process_image_path ~= ".*\\BitLockerToGo.exe")
| alter original_name = json_extract_scalar(action_process_file_info, "$.original_name")
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_process_cwd, action_process_image_sha256, action_process_image_md5, action_process_signature_product, action_process_image_auth_sha1, action_process_image_command_line, action_process_signature_vendor, action_process_integrity_level, action_process_username, action_process_image_path, actor_process_image_command_line, original_name
```

## When to use

Detects the execution of "BitLockerToGo.EXE".

## Variations

_(No variations are documented for this entry.)_
