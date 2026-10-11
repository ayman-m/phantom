---
id: XQL-517-cffa4b26
title: NetNTLM Downgrade Attack
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

# NetNTLM Downgrade Attack

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4
 | filter (action_registry_key_name contains "SYSTEM" AND action_registry_key_name contains "ControlSet" AND action_registry_key_name contains "\Control\Lsa") AND (action_registry_key_name ~= ".*\\lmcompatibilitylevel" OR action_registry_key_name ~= ".*\\NtlmMinClientSec" OR action_registry_key_name ~= ".*\\RestrictSendingNTLMTraffic")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name, action_registry_value_name
```

## When to use

Detects NetNTLM downgrade attack.

## Variations

_(No variations are documented for this entry.)_
