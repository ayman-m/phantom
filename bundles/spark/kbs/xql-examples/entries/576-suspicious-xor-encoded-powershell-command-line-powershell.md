---
id: XQL-576-6039644b
title: Suspicious XOR Encoded PowerShell Command Line - PowerShell
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

# Suspicious XOR Encoded PowerShell Command Line - PowerShell

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter (event_type = 31 and event_sub_type = 10) or (event_type = 15 and action_evtlog_event_id IN (4104)) | alter script_data = if (event_type = 15, action_evtlog_message , to_string(dynamic_event_string_map))
| filter (script_data contains "HostName=ConsoleHost") and (script_data contains "bxor" OR  script_data contains "char" OR  script_data contains "join")
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, script_data
```

## When to use

Detects suspicious powershell process which includes bxor command, alternative obfuscation method to b64 encoded commands.

## Variations

_(No variations are documented for this entry.)_
