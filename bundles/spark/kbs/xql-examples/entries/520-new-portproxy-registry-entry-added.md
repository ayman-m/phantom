---
id: XQL-520-79247561
title: New PortProxy Registry Entry Added
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

# New PortProxy Registry Entry Added

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4
 | filter (action_registry_key_name contains "\Services\PortProxy\v4tov4\tcp")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name, action_registry_value_name
```

## When to use

Detects the modification of the PortProxy registry key which is used for port forwarding.

## Variations

_(No variations are documented for this entry.)_
