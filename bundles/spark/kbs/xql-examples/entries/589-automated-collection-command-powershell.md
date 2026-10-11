---
id: XQL-589-f71e24c9
title: Automated Collection Command PowerShell
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

# Automated Collection Command PowerShell

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter (event_type = 31 and event_sub_type = 10) or (event_type = 15 and action_evtlog_event_id IN (4104)) | alter script_data = if (event_type = 15, action_evtlog_message , to_string(dynamic_event_string_map))
| filter (((script_data contains ".doc" OR  script_data contains ".docx" OR  script_data contains ".xls" OR  script_data contains ".xlsx" OR  script_data contains ".ppt" OR  script_data contains ".pptx" OR  script_data contains ".rtf" OR  script_data contains ".pdf" OR  script_data contains ".txt")) AND ((script_data contains "Get-ChildItem" AND  script_data contains " -Recurse " AND  script_data contains " -Include ")))
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, script_data
```

## When to use

Detect Automated Collection Command via PowerShell.

## Variations

_(No variations are documented for this entry.)_
