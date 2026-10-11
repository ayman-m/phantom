---
id: XQL-573-522cee69
title: Zip A Folder With PowerShell For Staging In Temp - PowerShell
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

# Zip A Folder With PowerShell For Staging In Temp - PowerShell

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter (event_type = 31 and event_sub_type = 10) or (event_type = 15 and action_evtlog_event_id IN (4104)) | alter script_data = if (event_type = 15, action_evtlog_message , to_string(dynamic_event_string_map))
| filter (script_data contains "Compress-Archive -Path*-DestinationPath $env:TEMP" OR  script_data contains "Compress-Archive -Path*-DestinationPath*\AppData\Local\Temp" OR  script_data contains "Compress-Archive -Path*-DestinationPath*:\Windows\Temp")
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, script_data
```

## When to use

Detects PowerShell scripts that make use of the "Compress-Archive" Cmdlet in order to compress folders and files where the output is stored in a potentially suspicious location that is used often by malware for exfiltration.

## Variations

_(No variations are documented for this entry.)_
