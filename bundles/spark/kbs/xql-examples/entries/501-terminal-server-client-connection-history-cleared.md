---
id: XQL-501-482d2094
title: Terminal Server Client Connection History Cleared
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

# Terminal Server Client Connection History Cleared

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4 and event_sub_type = 2
 | filter (((action_registry_key_name contains "\Microsoft\Terminal Server Client\Default\MRU")) OR ((action_registry_key_name contains "\Microsoft\Terminal Server Client\Servers")))
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name
```

## When to use

Detects the deletion of registry keys containing the MSTSC connection history.

## Variations

_(No variations are documented for this entry.)_
