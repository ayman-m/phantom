---
id: XQL-241-79246c08
title: Solarwinds infected process drops executable to disk
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - dedup
  - xdr_data
  - source:dataset
---

# Solarwinds infected process drops executable to disk

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // go over xdr data
|filter event_type = ENUM.FILE and event_sub_type = ENUM.FILE_WRITE // go over file write events
|filter lowercase(actor_process_image_name) = "solarwinds.businesslayerhost*.exe" // limit to solarwinds infected process
|filter  action_file_extension in ("dll", "exe", "sys", "msi", "scr", "ocx", "cmd", "bat", "ps1", "vba", "vbs", "com", "cpl", "bin", "vbe") // select known binary file extensions
|fields causality_actor_process_image_path, actor_process_image_path, agent_hostname, action_file_path, action_file_name // select presented fields
|dedup causality_actor_process_image_path, actor_process_image_path, agent_hostname, action_file_name // dedup the data on specific file names
```

## When to use

Displays files dropped by the infected Solarwinds executables

## Variations

_(No variations are documented for this entry.)_
