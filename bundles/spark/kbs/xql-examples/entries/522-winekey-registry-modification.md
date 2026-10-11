---
id: XQL-522-8646ef60
title: WINEKEY Registry Modification
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

# WINEKEY Registry Modification

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4
 | filter (action_registry_key_name ~= ".*Software\\Microsoft\\Windows\\CurrentVersion\\Run\\Backup Mgr")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name, action_registry_value_name
```

## When to use

Detects potential malicious modification of run keys by winekey or team9 backdoor.

## Variations

_(No variations are documented for this entry.)_
