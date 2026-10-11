---
id: XQL-495-685081aa
title: Potential Persistence Via Logon Scripts
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

# Potential Persistence Via Logon Scripts

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4 and event_sub_type = 1
 | filter (action_registry_key_name contains "UserInitMprLogonScript")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name
```

## When to use

Detects creation of UserInitMprLogonScript registry value which can be used as a persistence method by malicious actors.

## Variations

_(No variations are documented for this entry.)_
