---
id: XQL-518-e4963b97
title: Office Application Startup - Office Test
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
  - Registry
  - Misconfiguration
  - Process
---

# Office Application Startup - Office Test

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4
 | filter (action_registry_key_name contains "\Software\Microsoft\Office test\Special\Perf")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name, action_registry_value_name
```

## When to use

Detects the addition of office test registry that allows a user to specify an arbitrary DLL that will be executed every time an Office application is started.

## Variations

_(No variations are documented for this entry.)_
