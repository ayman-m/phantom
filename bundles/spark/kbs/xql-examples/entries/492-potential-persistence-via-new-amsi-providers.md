---
id: XQL-492-0f49987a
title: Potential Persistence Via New AMSI Providers
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

# Potential Persistence Via New AMSI Providers

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4 and event_sub_type = 1
 | filter (action_registry_key_name contains "\SOFTWARE\Microsoft\AMSI\Providers" OR action_registry_key_name contains "\SOFTWARE\WOW6432Node\Microsoft\AMSI\Providers") and not (actor_process_image_path ~= "C:\\Windows\\System32\\.*" OR actor_process_image_path ~= "C:\\Program Files\\.*" OR actor_process_image_path ~= "C:\\Program Files (x86)\\.*")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name
```

## When to use

Detects when an attacker registers a new AMSI provider in order to achieve persistence.

## Variations

_(No variations are documented for this entry.)_
