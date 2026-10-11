---
id: XQL-510-f30739e9
title: Wdigest CredGuard Registry Modification
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

# Wdigest CredGuard Registry Modification

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4
 | filter (action_registry_key_name ~= ".*\\IsCredGuardEnabled")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name, action_registry_value_name
```

## When to use

Detects potential malicious modification of the property value of IsCredGuardEnabled from HKLM:\SYSTEM\CurrentControlSet\Control\SecurityProviders\WDigest to disable Cred Guard on a system.

## Variations

_(No variations are documented for this entry.)_
