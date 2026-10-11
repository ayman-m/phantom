---
id: XQL-588-a73f2452
title: Potential Data Exfiltration Via Audio File
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

# Potential Data Exfiltration Via Audio File

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter (event_type = 31 and event_sub_type = 10) or (event_type = 15 and action_evtlog_event_id IN (4104)) | alter script_data = if (event_type = 15, action_evtlog_message , to_string(dynamic_event_string_map))
| filter (script_data contains "[System.Math]::" AND  script_data contains "[IO.FileMode]::" AND  script_data contains "BinaryWriter") and (((script_data contains "0x52" AND  script_data contains "0x49" AND  script_data contains "0x46" AND  script_data contains "0x57" AND  script_data contains "0x41" AND  script_data contains "0x56" AND  script_data contains "0x45" AND  script_data contains "0xAC")))
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, script_data
```

## When to use

Detects potential exfiltration attempt via audio file using PowerShell.

## Variations

_(No variations are documented for this entry.)_
