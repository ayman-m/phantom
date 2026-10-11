---
id: XQL-566-d4ad4015
title: PowerShell Called from an Executable Version Mismatch
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

# PowerShell Called from an Executable Version Mismatch

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter (event_type = 31 and event_sub_type = 10) or (event_type = 15 and action_evtlog_event_id IN (4104)) | alter script_data = if (event_type = 15, action_evtlog_message , to_string(dynamic_event_string_map))
| filter (((script_data contains "EngineVersion=2." OR  script_data contains "EngineVersion=4." OR  script_data contains "EngineVersion=5.")) AND ((script_data contains "HostVersion=3.")))
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, script_data
```

## When to use

Detects PowerShell called from an executable by the version mismatch method.

## Variations

_(No variations are documented for this entry.)_
