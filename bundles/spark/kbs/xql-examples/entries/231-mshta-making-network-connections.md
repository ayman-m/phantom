---
id: XQL-231-dff0ed35
title: Mshta making network connections
category: investigation
dataset: network_story
tags:
  - preset
  - filter
  - fields
  - network_story
  - source:preset
---

# Mshta making network connections

**Dataset**: `network_story`

```sql
preset = network_story // Using XDR network story preset
| filter actor_process_image_name  = "mshta.exe"  // Filtering by process name is mshta.exe 
| fields actor_process_image_path as process_path, actor_process_command_line as process_cmd, action_local_ip as source_ip, action_local_port as source_port, action_remote_ip as remote_ip, action_remote_port as remote_port, action_total_upload as upload, action_total_download as download // Selecting relevant fields
```

## When to use

Displays all network connections made by mshta.exe

## Variations

_(No variations are documented for this entry.)_
