---
id: XQL-579-be49c02c
title: AADInternals PowerShell Cmdlets Execution - PsScript
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

# AADInternals PowerShell Cmdlets Execution - PsScript

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter (event_type = 31 and event_sub_type = 10) or (event_type = 15 and action_evtlog_event_id IN (4104)) | alter script_data = if (event_type = 15, action_evtlog_message , to_string(dynamic_event_string_map))
| filter (script_data contains "Add-AADInt" OR  script_data contains "ConvertTo-AADInt" OR  script_data contains "Disable-AADInt" OR  script_data contains "Enable-AADInt" OR  script_data contains "Export-AADInt" OR  script_data contains "Get-AADInt" OR  script_data contains "Grant-AADInt" OR  script_data contains "Install-AADInt" OR  script_data contains "Invoke-AADInt" OR  script_data contains "Join-AADInt" OR  script_data contains "New-AADInt" OR  script_data contains "Open-AADInt" OR  script_data contains "Read-AADInt" OR  script_data contains "Register-AADInt" OR  script_data contains "Remove-AADInt" OR  script_data contains "Restore-AADInt" OR  script_data contains "Search-AADInt" OR  script_data contains "Send-AADInt" OR  script_data contains "Set-AADInt" OR  script_data contains "Start-AADInt" OR  script_data contains "Update-AADInt")
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, script_data
```

## When to use

Detects ADDInternals Cmdlet execution. A tool for administering Azure AD and Office 365.

## Variations

_(No variations are documented for this entry.)_
