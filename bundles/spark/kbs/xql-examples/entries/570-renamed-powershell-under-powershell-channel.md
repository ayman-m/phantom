---
id: XQL-570-9a47207b
title: Renamed Powershell Under Powershell Channel
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

# Renamed Powershell Under Powershell Channel

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter (event_type = 31 and event_sub_type = 10) or (event_type = 15 and action_evtlog_event_id IN (4104)) | alter script_data = if (event_type = 15, action_evtlog_message , to_string(dynamic_event_string_map))
| filter (script_data contains "HostName=ConsoleHost") and not (((script_data contains "HostApplication=powershell" OR  script_data contains "HostApplication=C:\Windows\System32\WindowsPowerShell\v1.0\powershell" OR  script_data contains "HostApplication=C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell" OR  script_data contains "HostApplication=C:/Windows/System32/WindowsPowerShell/v1.0/powershell" OR  script_data contains "HostApplication=C:/Windows/SysWOW64/WindowsPowerShell/v1.0/powershell")) OR ((script_data ~= "HostId=[a-zA-Z0-9-]{36} EngineVersion=")))
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, script_data
```

## When to use

Detects a renamed Powershell execution.

## Variations

_(No variations are documented for this entry.)_
