---
id: XQL-509-7029196d
title: CMSTP Execution Registry Event
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

# CMSTP Execution Registry Event

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4
 | filter (action_registry_key_name contains "\cmmgr32.exe")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name, action_registry_value_name
```

## When to use

Detects various indicators of Microsoft Connection Manager Profile Installer execution.

## Variations

_(No variations are documented for this entry.)_
