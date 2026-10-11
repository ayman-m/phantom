---
id: XQL-532-1bc5bcf9
title: Enable Remote Connection Between Anonymous Computer - AllowAnonymousCallback
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

# Enable Remote Connection Between Anonymous Computer - AllowAnonymousCallback

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4
 | filter (action_registry_key_name contains "\Microsoft\WBEM\CIMOM\AllowAnonymousCallback") AND (action_registry_value_name IN ("DWORD (0x00000001)"))
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name, action_registry_value_name
```

## When to use

Detects enabling of the AllowAnonymousCallback registry value, which allows a remote connection between computers that do not have a trust relationship.

## Variations

_(No variations are documented for this entry.)_
