---
id: XQL-255-4e3a8975
title: Servers compressed files and dumps
category: investigation
dataset: xdr_data
tags:
  - config
  - filter
  - xdr_data
  - source:dataset
---

# Servers compressed files and dumps

**Dataset**: `xdr_data`

```sql
config case_sensitive = false
| dataset = xdr_data // XDR data
|filter event_type = ENUM.FILE and event_sub_type in (ENUM.FILE_CREATE_NEW, ENUM.FILE_WRITE) // filter on writes
|filter agent_os_sub_type contains "server"  // filter on servers
|filter action_file_path ~= "c:\\programdata\\[a-zA-Z0-9]+\.(rar|zip|zipx|7z)" OR action_file_path ~= "(c:\\root\\[a-zA-Z0-9]+\.dmp$|c:\\windows\\temp\\[a-zA-Z0-9]+\.dmp$)" // look for suspicious paths and extensions
```

## When to use

Displays compressed and dumps files in abused locations that might be used for staging

## Variations

_(No variations are documented for this entry.)_
