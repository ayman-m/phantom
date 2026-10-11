---
id: XQL-595-314042f1
title: File Download Via Bitsadmin
category: investigation
dataset: xdr_data
tags:
  - filter
  - alter
  - fields
  - xdr_data
  - source:dataset
  - Process
  - Network
---

# File Download Via Bitsadmin

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = 1 and event_sub_type = 1
| filter (action_process_image_path ~= ".*\\bitsadmin.exe") AND (json_extract_scalar(action_process_file_info, "$.original_name") IN ("bitsadmin.exe")) and ((action_process_image_command_line contains " /transfer ") or (((action_process_image_command_line contains " /create " OR  action_process_image_command_line contains " /addfile ")) AND ((action_process_image_command_line contains "http"))))
| alter original_name = json_extract_scalar(action_process_file_info, "$.original_name")
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_process_cwd, action_process_image_sha256, action_process_image_md5, action_process_signature_product, action_process_image_auth_sha1, action_process_image_command_line, action_process_signature_vendor, action_process_integrity_level, action_process_username, action_process_image_path, actor_process_image_command_line, original_name
```

## When to use

Detects usage of bitsadmin downloading a file.

## Variations

_(No variations are documented for this entry.)_
