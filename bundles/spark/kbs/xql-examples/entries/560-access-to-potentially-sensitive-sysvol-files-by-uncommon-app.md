---
id: XQL-560-0127ce19
title: Access To Potentially Sensitive Sysvol Files By Uncommon Applications
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
  - Malware
---

# Access To Potentially Sensitive Sysvol Files By Uncommon Applications

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = 3
| filter (action_file_path ~= "\\\\.*") AND (action_file_path contains "\sysvol" AND  action_file_path contains "\Policies") AND (action_file_path ~= ".*audit.csv" OR  action_file_path ~= ".*Files.xml" OR  action_file_path ~= ".*GptTmpl.inf" OR  action_file_path ~= ".*groups.xml" OR  action_file_path ~= ".*Registry.pol" OR  action_file_path ~= ".*Registry.xml" OR  action_file_path ~= ".*scheduledtasks.xml" OR  action_file_path ~= ".*scripts.ini" OR  action_file_path ~= ".*services.xml") and not (((actor_process_image_path ~= "C:\\Program Files (x86)\\.*" OR  actor_process_image_path ~= "C:\\Program Files\\.*" OR  actor_process_image_path ~= "C:\\Windows\\system32\\.*" OR  actor_process_image_path ~= "C:\\Windows\\SysWOW64\\.*")) OR ((actor_process_image_path IN ("C:\Windows\explorer.exe"))))
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_file_path
```

## When to use

Detects file access requests to potentially sensitive files hosted on the Windows Sysvol share.

## Variations

_(No variations are documented for this entry.)_
