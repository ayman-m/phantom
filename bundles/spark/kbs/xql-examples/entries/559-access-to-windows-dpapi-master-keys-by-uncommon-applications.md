---
id: XQL-559-dd3132ff
title: Access To Windows DPAPI Master Keys By Uncommon Applications
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
  - Malware
---

# Access To Windows DPAPI Master Keys By Uncommon Applications

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = 3
| filter (action_file_path contains "\Microsoft\Protect\S-1-5-18" OR  action_file_path contains "\Microsoft\Protect\S-1-5-21-") and not (((actor_process_image_path ~= "C:\\Program Files\\.*" OR  actor_process_image_path ~= "C:\\Program Files (x86)\\.*" OR  actor_process_image_path ~= "C:\\Windows\\system32\\.*" OR  actor_process_image_path ~= "C:\\Windows\\SysWOW64\\.*")))
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_file_path
```

## When to use

Detects file access requests to the the Windows Data Protection API Master keys by an uncommon application.

## Variations

_(No variations are documented for this entry.)_
