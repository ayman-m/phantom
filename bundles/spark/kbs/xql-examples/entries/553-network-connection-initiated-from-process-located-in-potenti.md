---
id: XQL-553-0841417d
title: Network Connection Initiated From Process Located In Potentially Suspicious Or Uncommon Location
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
  - Network
  - Executable
---

# Network Connection Initiated From Process Located In Potentially Suspicious Or Uncommon Location

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = 2 and event_sub_type in (2,5,8,11)
| filter (actor_process_image_path contains ":\$Recycle.bin" OR  actor_process_image_path contains ":\Perflogs" OR  actor_process_image_path contains ":\Temp" OR  actor_process_image_path contains ":\Users\Default" OR  actor_process_image_path contains ":\Windows\Fonts" OR  actor_process_image_path contains ":\Windows\IME" OR  actor_process_image_path contains ":\Windows\System32\Tasks" OR  actor_process_image_path contains ":\Windows\Tasks" OR  actor_process_image_path contains "\config\systemprofile" OR  actor_process_image_path contains "\Windows\addins") and not (((dst_agent_hostname ~= ".*.githubusercontent.com" OR  dst_agent_hostname ~= ".*anonfiles.com" OR  dst_agent_hostname ~= ".*cdn.discordapp.com" OR  dst_agent_hostname ~= ".*ddns.net" OR  dst_agent_hostname ~= ".*dl.dropboxusercontent.com" OR  dst_agent_hostname ~= ".*ghostbin.co" OR  dst_agent_hostname ~= ".*glitch.me" OR  dst_agent_hostname ~= ".*gofile.io" OR  dst_agent_hostname ~= ".*hastebin.com" OR  dst_agent_hostname ~= ".*mediafire.com" OR  dst_agent_hostname ~= ".*mega.co.nz" OR  dst_agent_hostname ~= ".*mega.nz" OR  dst_agent_hostname ~= ".*onrender.com" OR  dst_agent_hostname ~= ".*pages.dev" OR  dst_agent_hostname ~= ".*paste.ee" OR  dst_agent_hostname ~= ".*pastebin.com" OR  dst_agent_hostname ~= ".*pastebin.pl" OR  dst_agent_hostname ~= ".*pastetext.net" OR  dst_agent_hostname ~= ".*portmap.io" OR  dst_agent_hostname ~= ".*privatlab.com" OR  dst_agent_hostname ~= ".*privatlab.net" OR  dst_agent_hostname ~= ".*send.exploit.in" OR  dst_agent_hostname ~= ".*sendspace.com" OR  dst_agent_hostname ~= ".*storage.googleapis.com" OR  dst_agent_hostname ~= ".*storjshare.io" OR  dst_agent_hostname ~= ".*supabase.co" OR  dst_agent_hostname ~= ".*temp.sh" OR  dst_agent_hostname ~= ".*transfer.sh" OR  dst_agent_hostname ~= ".*trycloudflare.com" OR  dst_agent_hostname ~= ".*ufile.io" OR  dst_agent_hostname ~= ".*w3spaces.com" OR  dst_agent_hostname ~= ".*workers.dev")))
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_local_port, action_remote_port, dst_agent_hostname, action_local_ip, action_remote_ip, actor_process_image_command_line, action_network_dpi_fields
```

## When to use

Detects executables located in potentially suspicious directories initiating network connections towards file sharing domains.

## Variations

_(No variations are documented for this entry.)_
