---
id: XQL-549-0756944d
title: Office Application Initiated Network Connection Over Uncommon Ports
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
  - Network
---

# Office Application Initiated Network Connection Over Uncommon Ports

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = 2 and event_sub_type in (2,5,8,11)
| filter (actor_process_image_path ~= ".*\\excel.exe" OR  actor_process_image_path ~= ".*\\outlook.exe" OR  actor_process_image_path ~= ".*\\powerpnt.exe" OR  actor_process_image_path ~= ".*\\winword.exe" OR  actor_process_image_path ~= ".*\\wordview.exe") and not (((action_remote_port IN (53, 80, 139, 443, 445))) OR ((actor_process_image_path contains ":\Program Files\Microsoft Office") AND (actor_process_image_path ~= ".*\\OUTLOOK.EXE") AND (action_remote_port IN (143, 465, 587, 993, 995))))
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_local_port, action_remote_port, dst_agent_hostname, action_local_ip, action_remote_ip, actor_process_image_command_line, action_network_dpi_fields
```

## When to use

Detects an office suit application (Word, Excel, PowerPoint, Outlook) communicating to target systems over uncommon ports.

## Variations

_(No variations are documented for this entry.)_
