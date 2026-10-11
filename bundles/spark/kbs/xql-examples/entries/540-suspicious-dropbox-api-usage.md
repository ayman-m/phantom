---
id: XQL-540-bae49edb
title: Suspicious Dropbox API Usage
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
  - Network
---

# Suspicious Dropbox API Usage

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = 2 and event_sub_type in (2,5,8,11)
| filter (dst_agent_hostname ~= ".*api.dropboxapi.com" OR  dst_agent_hostname ~= ".*content.dropboxapi.com") and not (((actor_process_image_path contains "\Dropbox")))
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_local_port, action_remote_port, dst_agent_hostname, action_local_ip, action_remote_ip, actor_process_image_command_line, action_network_dpi_fields
```

## When to use

Detects an executable that isn't dropbox but communicates with the Dropbox API.

## Variations

_(No variations are documented for this entry.)_
