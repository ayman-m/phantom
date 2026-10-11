---
id: XQL-233-1988a1ce
title: Regsvr32 making network connections
category: investigation
dataset: network_story
tags:
  - preset
  - filter
  - alter
  - fields
  - network_story
  - source:preset
---

# Regsvr32 making network connections

**Dataset**: `network_story`

```sql
preset = network_story  // Using XDR network story preset
| filter actor_process_image_name = "regsvr32.exe" // Looking for regsvr32 making connections 
| alter app_id = arraystring(action_app_id_transitions,",") // Turning the app-id fields from an array to a string for easy viewing
| fields actor_process_image_name as process_name, actor_process_command_line as process_cmd, agent_hostname as agent_name, action_local_ip as source_ip, action_local_port as source_port, action_remote_ip as remote_ip, action_remote_port as remote_port,app_id,  action_total_upload as upload, action_total_download as download // Selecting relevant fields
```

## When to use

Displays all network connections made by regsvr32.exe

## Variations

_(No variations are documented for this entry.)_
