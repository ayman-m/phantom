---
id: XQL-496-cd043492
title: PUA - Sysinternal Tool Execution
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

# PUA - Sysinternal Tool Execution

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4 and event_sub_type = 1
 | filter (action_registry_key_name ~= ".*\\EulaAccepted")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name
```

## When to use

Detects the execution of a Sysinternals Tool via the creation of the accepteula registry key.

## Variations

_(No variations are documented for this entry.)_
