---
id: XQL-508-38561a77
title: UAC Bypass Via Wsreset
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

# UAC Bypass Via Wsreset

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4
 | filter (action_registry_key_name ~= ".*\\AppX82a6gwre4fdg3bt635tn5ctqjf8msdd2\\Shell\\open\\command")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name, action_registry_value_name
```

## When to use

Detects Usage of Unfixed method for UAC bypass from Windows 10.

## Variations

_(No variations are documented for this entry.)_
