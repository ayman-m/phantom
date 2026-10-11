---
id: XQL-555-dc3993c3
title: Suspicious Wordpad Outbound Connections
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
  - Network
  - Executable
---

# Suspicious Wordpad Outbound Connections

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = 2 and event_sub_type in (2,5,8,11)
| filter (actor_process_image_path ~= ".*\\wordpad.exe") and not (((action_remote_port IN (80, 139, 443, 445, 465, 587, 993, 995))))
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_local_port, action_remote_port, dst_agent_hostname, action_local_ip, action_remote_ip, actor_process_image_command_line, action_network_dpi_fields
```

## When to use

Detects a network connection initiated by "wordpad.exe" over uncommon destination ports.

## Variations

_(No variations are documented for this entry.)_
