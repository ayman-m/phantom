---
id: XQL-562-20b8b692
title: Unusual File Modification by dns.exe
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
  - Network
  - Process
---

# Unusual File Modification by dns.exe

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = 3 and event_sub_type = 6
| filter (actor_process_image_path ~= ".*\\dns.exe") and not (action_file_path ~= ".*\\dns.log")
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_file_path
```

## When to use

Detects an unexpected file being modified by dns.exe which my indicate activity related to remote code execution or other forms of exploitation as seen in CVE-2020-1350 (SigRed).

## Variations

_(No variations are documented for this entry.)_
