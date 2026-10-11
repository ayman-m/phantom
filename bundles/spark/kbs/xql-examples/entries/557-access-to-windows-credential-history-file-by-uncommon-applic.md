---
id: XQL-557-46b29b96
title: Access To Windows Credential History File By Uncommon Applications
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
  - Malware
---

# Access To Windows Credential History File By Uncommon Applications

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = 3
| filter (action_file_path ~= ".*\\Microsoft\\Protect\\CREDHIST") and not (((actor_process_image_path ~= "C:\\Program Files\\.*" OR  actor_process_image_path ~= "C:\\Program Files (x86)\\.*" OR  actor_process_image_path ~= "C:\\Windows\\system32\\.*" OR  actor_process_image_path ~= "C:\\Windows\\SysWOW64\\.*")) OR ((actor_process_image_path IN ("C:\Windows\explorer.exe"))))
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_file_path
```

## When to use

Detects file access requests to the Windows Credential History File by an uncommon application.

## Variations

_(No variations are documented for this entry.)_
