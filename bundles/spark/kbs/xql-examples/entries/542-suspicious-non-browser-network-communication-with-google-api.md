---
id: XQL-542-d54728a7
title: Suspicious Non-Browser Network Communication With Google API
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
  - Network
  - IOC
  - Process
---

# Suspicious Non-Browser Network Communication With Google API

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = 2 and event_sub_type in (2,5,8,11)
| filter (dst_agent_hostname contains "drive.googleapis.com" OR  dst_agent_hostname contains "oauth2.googleapis.com" OR  dst_agent_hostname contains "sheets.googleapis.com" OR  dst_agent_hostname contains "www.googleapis.com") and not (((actor_process_image_path IN (null))) OR ((actor_process_image_path IN (null)))) and not (((actor_process_image_path ~= ".*\\brave.exe")) OR ((actor_process_image_path ~= ".*:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" OR  actor_process_image_path ~= ".*:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe")) OR ((actor_process_image_path contains ":\Program Files\Google\Drive File Stream") AND (actor_process_image_path ~= ".*\\GoogleDriveFS.exe")) OR ((actor_process_image_path ~= ".*:\\Program Files\\Mozilla Firefox\\firefox.exe" OR  actor_process_image_path ~= ".*:\\Program Files (x86)\\Mozilla Firefox\\firefox.exe")) OR ((actor_process_image_path ~= ".*:\\Program Files (x86)\\Internet Explorer\\iexplore.exe" OR  actor_process_image_path ~= ".*:\\Program Files\\Internet Explorer\\iexplore.exe")) OR ((actor_process_image_path ~= ".*\\maxthon.exe")) OR ((actor_process_image_path contains ":\Program Files (x86)\Microsoft\EdgeWebView\Application") AND (actor_process_image_path ~= ".*:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe" OR  actor_process_image_path ~= ".*:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe" OR  actor_process_image_path ~= ".*\\WindowsApps\\MicrosoftEdge.exe")) OR ((actor_process_image_path contains ":\Program Files (x86)\Microsoft\EdgeCore" OR  actor_process_image_path contains ":\Program Files\Microsoft\EdgeCore") AND (actor_process_image_path ~= ".*\\msedge.exe" OR  actor_process_image_path ~= ".*\\msedgewebview2.exe")) OR ((actor_process_image_path ~= ".*\\opera.exe")) OR ((actor_process_image_path ~= ".*\\safari.exe")) OR ((actor_process_image_path ~= ".*\\seamonkey.exe")) OR ((actor_process_image_path ~= ".*\\vivaldi.exe")) OR ((actor_process_image_path ~= ".*\\whale.exe")) OR ((actor_process_image_path ~= ".*\\GoogleUpdate.exe")) OR ((actor_process_image_path ~= ".*\\outlook.exe")))
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_local_port, action_remote_port, dst_agent_hostname, action_local_ip, action_remote_ip, actor_process_image_command_line, action_network_dpi_fields
```

## When to use

Detects a non-browser process interacting with the Google API which could indicate the use of a covert C2 such as Google Sheet C2 (GC2-sheet).

## Variations

_(No variations are documented for this entry.)_
