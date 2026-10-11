---
id: XQL-585-4adafe28
title: AMSI Bypass Pattern Assembly GetType
category: investigation
dataset: xdr_data
tags:
  - filter
  - alter
  - fields
  - xdr_data
  - source:dataset
  - PowerShell
---

# AMSI Bypass Pattern Assembly GetType

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter (event_type = 31 and event_sub_type = 10) or (event_type = 15 and action_evtlog_event_id IN (4104)) | alter script_data = if (event_type = 15, action_evtlog_message , to_string(dynamic_event_string_map))
| filter (script_data contains "[Ref].Assembly.GetType" AND  script_data contains "SetValue($null,$true)" AND  script_data contains "NonPublic,Static")
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, script_data
```

## When to use

Detects code fragments found in small and obfuscated AMSI bypass PowerShell scripts.

## Variations

_(No variations are documented for this entry.)_
