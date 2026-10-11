---
id: XQL-596-d3009c0f
title: Suspicious Download From File-Sharing Website Via Bitsadmin
category: investigation
dataset: xdr_data
tags:
  - filter
  - alter
  - fields
  - xdr_data
  - source:dataset
  - Process
  - Network
---

# Suspicious Download From File-Sharing Website Via Bitsadmin

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = 1 and event_sub_type = 1
| filter (((action_process_image_path ~= ".*\\bitsadmin.exe") AND (json_extract_scalar(action_process_file_info, "$.original_name") IN ("bitsadmin.exe"))) AND ((action_process_image_command_line contains " /transfer " OR  action_process_image_command_line contains " /create " OR  action_process_image_command_line contains " /addfile ")) AND ((action_process_image_command_line contains ".githubusercontent.com" OR  action_process_image_command_line contains "anonfiles.com" OR  action_process_image_command_line contains "cdn.discordapp.com" OR  action_process_image_command_line contains "ddns.net" OR  action_process_image_command_line contains "dl.dropboxusercontent.com" OR  action_process_image_command_line contains "ghostbin.co" OR  action_process_image_command_line contains "glitch.me" OR  action_process_image_command_line contains "gofile.io" OR  action_process_image_command_line contains "hastebin.com" OR  action_process_image_command_line contains "mediafire.com" OR  action_process_image_command_line contains "mega.nz" OR  action_process_image_command_line contains "onrender.com" OR  action_process_image_command_line contains "pages.dev" OR  action_process_image_command_line contains "paste.ee" OR  action_process_image_command_line contains "pastebin.com" OR  action_process_image_command_line contains "pastebin.pl" OR  action_process_image_command_line contains "pastetext.net" OR  action_process_image_command_line contains "privatlab.com" OR  action_process_image_command_line contains "privatlab.net" OR  action_process_image_command_line contains "send.exploit.in" OR  action_process_image_command_line contains "sendspace.com" OR  action_process_image_command_line contains "storage.googleapis.com" OR  action_process_image_command_line contains "storjshare.io" OR  action_process_image_command_line contains "supabase.co" OR  action_process_image_command_line contains "temp.sh" OR  action_process_image_command_line contains "transfer.sh" OR  action_process_image_command_line contains "trycloudflare.com" OR  action_process_image_command_line contains "ufile.io" OR  action_process_image_command_line contains "w3spaces.com" OR  action_process_image_command_line contains "workers.dev")))
| alter original_name = json_extract_scalar(action_process_file_info, "$.original_name")
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_process_cwd, action_process_image_sha256, action_process_image_md5, action_process_signature_product, action_process_image_auth_sha1, action_process_image_command_line, action_process_signature_vendor, action_process_integrity_level, action_process_username, action_process_image_path, actor_process_image_command_line, original_name
```

## When to use

Detects usage of bitsadmin downloading a file from a suspicious domain.

## Variations

_(No variations are documented for this entry.)_
