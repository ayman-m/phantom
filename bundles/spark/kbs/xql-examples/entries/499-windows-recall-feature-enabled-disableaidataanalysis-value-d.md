---
id: XQL-499-ebf3defc
title: Windows Recall Feature Enabled - DisableAIDataAnalysis Value Deleted
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

# Windows Recall Feature Enabled - DisableAIDataAnalysis Value Deleted

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4 and event_sub_type = 2
 | filter (action_registry_key_name ~= ".*\\Microsoft\\Windows\\WindowsAI\\DisableAIDataAnalysis")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name
```

## When to use

Detects the enabling of the Windows Recall feature via registry manipulation.

## Variations

_(No variations are documented for this entry.)_
