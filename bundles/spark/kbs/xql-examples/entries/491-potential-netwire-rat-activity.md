---
id: XQL-491-361aa3f5
title: Potential NetWire RAT Activity
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

# Potential NetWire RAT Activity

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4 and event_sub_type = 1
 | filter (action_registry_key_name contains "\software\NetWire")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name
```

## When to use

Detects registry keys related to NetWire RAT.

## Variations

_(No variations are documented for this entry.)_
