---
id: XQL-581-8c00ee2b
title: Potential Active Directory Enumeration Using AD Module - PsScript
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

# Potential Active Directory Enumeration Using AD Module - PsScript

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter (event_type = 31 and event_sub_type = 10) or (event_type = 15 and action_evtlog_event_id IN (4104)) | alter script_data = if (event_type = 15, action_evtlog_message , to_string(dynamic_event_string_map))
| filter (((script_data contains "Import-Module " AND  script_data contains "Microsoft.ActiveDirectory.Management.dll")) OR ((script_data contains "ipmo Microsoft.ActiveDirectory.Management.dll")))
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, script_data
```

## When to use

Detects usage of the "Import-Module" cmdlet to load the "Microsoft.ActiveDirectory.Management.dl" DLL.

## Variations

_(No variations are documented for this entry.)_
