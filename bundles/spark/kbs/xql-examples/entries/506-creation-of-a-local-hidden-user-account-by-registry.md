---
id: XQL-506-79ae5e13
title: Creation of a Local Hidden User Account by Registry
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

# Creation of a Local Hidden User Account by Registry

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4
 | filter (action_registry_key_name contains "\SAM\SAM\Domains\Account\Users\Names") AND (action_registry_key_name ~= ".*$") AND (actor_process_image_path ~= ".*\\lsass.exe")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name, action_registry_value_name
```

## When to use

Sysmon registry detection of a local hidden user account.

## Variations

_(No variations are documented for this entry.)_
