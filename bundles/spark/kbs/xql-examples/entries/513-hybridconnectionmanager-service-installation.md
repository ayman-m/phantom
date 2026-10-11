---
id: XQL-513-89e8414e
title: HybridConnectionManager Service Installation
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

# HybridConnectionManager Service Installation

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4
 | filter (action_registry_key_name contains "\Services\HybridConnectionManager") or (action_registry_value_name contains "Microsoft.HybridConnectionManager.Listener.exe")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name, action_registry_value_name
```

## When to use

Detects the installation of the Azure Hybrid Connection Manager service to allow remote code execution from Azure function.

## Variations

_(No variations are documented for this entry.)_
