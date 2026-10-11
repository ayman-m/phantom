---
id: XQL-515-2986544c
title: Path To Screensaver Binary Modified
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

# Path To Screensaver Binary Modified

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4
 | filter (action_registry_key_name ~= ".*\\Control Panel\\Desktop\\SCRNSAVE.EXE") and not (actor_process_image_path ~= ".*\\rundll32.exe" OR actor_process_image_path ~= ".*\\explorer.exe")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name, action_registry_value_name
```

## When to use

Detects value modification of registry key containing path to binary used as screensaver.

## Variations

_(No variations are documented for this entry.)_
