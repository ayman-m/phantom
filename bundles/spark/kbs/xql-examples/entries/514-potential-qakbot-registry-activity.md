---
id: XQL-514-a6f9c2ca
title: Potential Qakbot Registry Activity
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

# Potential Qakbot Registry Activity

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4
 | filter (action_registry_key_name ~= ".*\\Software\\firm\\soft\\Name")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name, action_registry_value_name
```

## When to use

Detects a registry key used by IceID in a campaign that distributes malicious OneNote files.

## Variations

_(No variations are documented for this entry.)_
