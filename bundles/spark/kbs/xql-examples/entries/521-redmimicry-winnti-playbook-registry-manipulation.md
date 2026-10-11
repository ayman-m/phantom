---
id: XQL-521-fb2ddf37
title: RedMimicry Winnti Playbook Registry Manipulation
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

# RedMimicry Winnti Playbook Registry Manipulation

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4
 | filter (action_registry_key_name contains "HKLM\SOFTWARE\Microsoft\HTMLHelp\data")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name, action_registry_value_name
```

## When to use

Detects actions caused by the RedMimicry Winnti playbook.

## Variations

_(No variations are documented for this entry.)_
