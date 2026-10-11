---
id: XQL-511-94493b16
title: Esentutl Volume Shadow Copy Service Keys
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

# Esentutl Volume Shadow Copy Service Keys

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4
 | filter (action_registry_key_name contains "System\CurrentControlSet\Services\VSS") AND (actor_process_image_path ~= ".*esentutl.exe") and not (action_registry_key_name contains "System\CurrentControlSet\Services\VSS\Start")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name, action_registry_value_name
```

## When to use

Detects the volume shadow copy service initialization and processing via esentutl.

## Variations

_(No variations are documented for this entry.)_
