---
id: XQL-556-131a80cd
title: Credential Manager Access By Uncommon Applications
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
  - Malware
---

# Credential Manager Access By Uncommon Applications

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = 3
| filter (action_file_path contains "\AppData\Local\Microsoft\Credentials" OR  action_file_path contains "\AppData\Roaming\Microsoft\Credentials" OR  action_file_path contains "\AppData\Local\Microsoft\Vault" OR  action_file_path contains "\ProgramData\Microsoft\Vault") and not (((actor_process_image_path ~= "C:\\Program Files\\.*" OR  actor_process_image_path ~= "C:\\Program Files (x86)\\.*" OR  actor_process_image_path ~= "C:\\Windows\\system32\\.*" OR  actor_process_image_path ~= "C:\\Windows\\SysWOW64\\.*")))
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_file_path
```

## When to use

Detects suspicious processes based on name and location that access the windows credential manager and vault, which can be a sign of credential stealing.

## Variations

_(No variations are documented for this entry.)_
