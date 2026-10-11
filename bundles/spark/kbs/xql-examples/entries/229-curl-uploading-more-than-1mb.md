---
id: XQL-229-a2759e44
title: Curl uploading more than 1MB
category: investigation
dataset: network_story
tags:
  - preset
  - filter
  - alter
  - fields
  - sort
  - network_story
  - source:preset
---

# Curl uploading more than 1MB

**Dataset**: `network_story`

```sql
preset = network_story // Using the network story preset
| filter actor_process_image_name contains "curl" and action_total_upload > 1048576 // Filtering for process contains curl and upload size is more than 1MB
| alter app_id = arraystring(action_app_id_transitions,",") // Turning the app-id fields from an array to a string for easy viewing
| fields actor_process_image_name as process_name, actor_process_command_line as process_cmd, action_local_ip as source_ip, action_local_port as source_port, action_remote_ip as remote_ip, action_remote_port as remote_port,app_id,  action_total_upload as upload // Selecting relevant fields
| sort desc upload // Sorting by upload size
```

## When to use

Display cases where curl is uploading more than 1MB to a remote server

## Variations

_(No variations are documented for this entry.)_
