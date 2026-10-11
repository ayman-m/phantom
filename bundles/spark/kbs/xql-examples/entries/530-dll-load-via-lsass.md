---
id: XQL-530-81e8e73d
title: DLL Load via LSASS
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

# DLL Load via LSASS

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4
 | filter (action_registry_key_name contains "\CurrentControlSet\Services\NTDS\DirectoryServiceExtPt" OR action_registry_key_name contains "\CurrentControlSet\Services\NTDS\LsaDbExtPt") and not (((actor_process_image_path IN ("C:\Windows\system32\lsass.exe")) AND (action_registry_value_name IN ("%%systemroot%%\system32\ntdsa.dll", "%%systemroot%%\system32\lsadb.dll"))))
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name, action_registry_value_name
```

## When to use

Detects a method to load DLL via LSASS process using an undocumented Registry key.

## Variations

_(No variations are documented for this entry.)_
