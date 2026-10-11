---
id: XQL-526-b962f60e
title: Security Support Provider (SSP) Added to LSA Configuration
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

# Security Support Provider (SSP) Added to LSA Configuration

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4
 | filter (action_registry_key_name ~= ".*\\Control\\Lsa\\Security Packages" OR action_registry_key_name ~= ".*\\Control\\Lsa\\OSConfig\\Security Packages") and not (((actor_process_image_path IN ("C:\Windows\system32\msiexec.exe", "C:\Windows\syswow64\MsiExec.exe"))))
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name, action_registry_value_name
```

## When to use

Detects the addition of a SSP to the registry.

## Variations

_(No variations are documented for this entry.)_
