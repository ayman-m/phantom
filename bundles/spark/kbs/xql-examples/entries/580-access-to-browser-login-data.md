---
id: XQL-580-584ee7b2
title: Access to Browser Login Data
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

# Access to Browser Login Data

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter (event_type = 31 and event_sub_type = 10) or (event_type = 15 and action_evtlog_event_id IN (4104)) | alter script_data = if (event_type = 15, action_evtlog_message , to_string(dynamic_event_string_map))
| filter (((script_data contains "Copy-Item" AND  script_data contains "-Destination")) AND ((script_data contains "\Opera Software\Opera Stable\Login Data" OR  script_data contains "\Mozilla\Firefox\Profiles" OR  script_data contains "\Microsoft\Edge\User Data\Default" OR  script_data contains "\Google\Chrome\User Data\Default\Login Data" OR  script_data contains "\Google\Chrome\User Data\Default\Login Data For Account")))
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, script_data
```

## When to use

Adversaries may acquire credentials from web browsers by reading files specific to the target browser.

## Variations

_(No variations are documented for this entry.)_
