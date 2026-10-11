---
id: XQL-505-6cc128dd
title: Removal Of SD Value to Hide Schedule Task
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
  - Registry
  - Misconfiguration
---

# Removal Of SD Value to Hide Schedule Task

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4 and event_sub_type = 2
 | filter (action_registry_key_name contains "\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Schedule\TaskCache\Tree" AND action_registry_key_name contains "SD")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name
```

## When to use

Detects Removal of SD (Security Descriptor) value in \Schedule\TaskCache\Tree registry hive to hide schedule task.

## Variations

_(No variations are documented for this entry.)_
