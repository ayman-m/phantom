---
id: XQL-516-2996348d
title: Narrator's Feedback-Hub Persistence
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

# Narrator's Feedback-Hub Persistence

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4
 | filter (((action_registry_key_name ~= ".*\\AppXypsaf9f1qserqevf0sws76dx4k9a5206\\Shell\\open\\command\\DelegateExecute")) OR ((action_registry_key_name ~= ".*\\AppXypsaf9f1qserqevf0sws76dx4k9a5206\\Shell\\open\\command\\(Default)")))
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name, action_registry_value_name
```

## When to use

Detects abusing Windows 10 Narrator's Feedback-Hub.

## Variations

_(No variations are documented for this entry.)_
