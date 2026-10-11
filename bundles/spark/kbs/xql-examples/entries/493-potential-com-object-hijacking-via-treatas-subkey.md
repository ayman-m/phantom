---
id: XQL-493-80daf2ca
title: Potential COM Object Hijacking Via TreatAs Subkey
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

# Potential COM Object Hijacking Via TreatAs Subkey

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4 and event_sub_type = 1
 | filter (action_registry_key_name contains "HKU" AND action_registry_key_name contains "Classes\CLSID" AND action_registry_key_name contains "\TreatAs") and not (((actor_process_image_path IN ("C:\WINDOWS\system32\svchost.exe"))))
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name
```

## When to use

Detects COM object hijacking via TreatAs subkey.

## Variations

_(No variations are documented for this entry.)_
