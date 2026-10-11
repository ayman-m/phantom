---
id: XQL-578-f13f279b
title: Alternate PowerShell Hosts - PowerShell Module
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

# Alternate PowerShell Hosts - PowerShell Module

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter (event_type = 31 and event_sub_type = 10) or (event_type = 15 and action_evtlog_event_id IN (4104)) | alter script_data = if (event_type = 15, action_evtlog_message , to_string(dynamic_event_string_map))
| filter (script_data contains "*") and not (((script_data contains "= powershell" OR  script_data contains "= C:\Windows\System32\WindowsPowerShell\v1.0\powershell" OR  script_data contains "= C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell" OR  script_data contains "= C:/Windows/System32/WindowsPowerShell/v1.0/powershell" OR  script_data contains "= C:/Windows/SysWOW64/WindowsPowerShell/v1.0/powershell")) OR ((script_data contains "= C:\WINDOWS\System32\sdiagnhost.exe -Embedding")) OR ((script_data contains "ConfigSyncRun.exe")) OR ((script_data contains "C:\Windows\system32\dsac.exe")) OR ((script_data contains "C:\Windows\system32\wsmprovhost.exe -Embedding")) OR ((script_data contains "Update-Help" OR  script_data contains "Failed to update Help for the module")))
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, script_data, script_data
```

## When to use

Detects alternate PowerShell hosts potentially bypassing detections looking for powershell.exe.

## Variations

_(No variations are documented for this entry.)_
