---
id: XQL-525-c64d92fd
title: Potential Credential Dumping Via LSASS SilentProcessExt Technique
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

# Potential Credential Dumping Via LSASS SilentProcessExt Technique

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4
 | filter (action_registry_key_name contains "Microsoft\Windows NT\CurrentVersion\SilentProcessExit\lsass.exe")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name, action_registry_value_name
```

## When to use

Detects changes to the Registry in which a monitor program gets registered to dump the memory of the lsass.exe process.

## Variations

_(No variations are documented for this entry.)_
