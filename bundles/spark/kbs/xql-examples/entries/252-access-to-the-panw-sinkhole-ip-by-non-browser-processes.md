---
id: XQL-252-1f08520c
title: Access to the PANW sinkhole IP by non-browser processes
category: investigation
dataset: network_story
tags:
  - preset
  - filter
  - fields
  - dedup
  - sort
  - network_story
  - source:preset
---

# Access to the PANW sinkhole IP by non-browser processes

**Dataset**: `network_story`

```sql
preset = network_story  // Using XDR network story preset
| filter action_remote_ip = "72.5.65.111" and lowercase(actor_process_image_name) not in ("chrome.exe", "msedge.exe","opera.exe", "firefox.exe", "iexplore.exe") // 72.5.65.111 is the default IP that is used to sinkhole in the NGFW. The filter also looks to exclude browsers since many ads are being sinkholed
| fields agent_hostname, action_local_ip, action_remote_ip, action_remote_port, dst_action_external_hostname, actor_process_image_path, actor_process_image_sha256, actor_process_command_line // selecting the relevant fields
| dedup agent_hostname, action_local_ip, action_remote_ip, action_remote_port, dst_action_external_hostname, actor_process_image_path, actor_process_image_sha256, actor_process_command_line  by asc _time // dedupping to only show the first time it happened
| sort desc _time  // sorting in desc order
```

## When to use

Displays any connections done by processes that are not browsers to the default sinkhole configured in the PANW NGFW

## Variations

_(No variations are documented for this entry.)_
