---
id: XQL-253-38914dce
title: Aspx file dropped by exchange or IIS
category: investigation
dataset: xdr_data
tags:
  - config
  - filter
  - fields
  - xdr_data
  - source:dataset
---

# Aspx file dropped by exchange or IIS

**Dataset**: `xdr_data`

```sql
config case_sensitive = false | dataset = xdr_data
| filter event_type = ENUM.FILE  and event_sub_type in (ENUM.FILE_WRITE, ENUM.FILE_CREATE_NEW) // Query file write events
| filter action_file_extension = "aspx" // query only aspx extension drops
| filter action_file_path ~= "(\\inetpub\\wwwroot\\aspnet_client\\|\\frontend\\httpproxy\\owa\\auth\\|\\frontend\\httpproxy\\ecp\\auth\\)" // look for OWA and generic IIS paths
| filter action_file_path != "*\\frontend\\httpproxy\\ecp\\auth\\timeoutlogoff.aspx" // ignore a standard file that is being used by OWA
| filter actor_process_image_name in ("UMWorkerProcess.exe", "w3wp.exe", "umservice.exe") // look for exchange and IIS processes
| fields agent_hostname, actor_process_image_path, actor_process_image_command_line, action_file_path
```

## When to use

Displays possible web shells dropped by exchange and IIS

## Variations

_(No variations are documented for this entry.)_
