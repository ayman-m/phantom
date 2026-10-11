---
id: XQL-519-a014e61b
title: Windows Registry Trust Record Modification
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

# Windows Registry Trust Record Modification

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4
 | filter (action_registry_key_name contains "\Security\Trusted Documents\TrustRecords")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name, action_registry_value_name
```

## When to use

Alerts on trust record modification within the registry, indicating usage of macros.

## Variations

_(No variations are documented for this entry.)_
