---
id: XQL-546-e5ecd0a7
title: Detects Communication To Ngrok Tunneling Service Initiated
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

# Detects Communication To Ngrok Tunneling Service Initiated

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = 2 and event_sub_type in (2,5,8,11)
| filter (dst_agent_hostname contains "tunnel.us.ngrok.com" OR  dst_agent_hostname contains "tunnel.eu.ngrok.com" OR  dst_agent_hostname contains "tunnel.ap.ngrok.com" OR  dst_agent_hostname contains "tunnel.au.ngrok.com" OR  dst_agent_hostname contains "tunnel.sa.ngrok.com" OR  dst_agent_hostname contains "tunnel.jp.ngrok.com" OR  dst_agent_hostname contains "tunnel.in.ngrok.com")
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_local_port, action_remote_port, dst_agent_hostname, action_local_ip, action_remote_ip, actor_process_image_command_line, action_network_dpi_fields
```

## When to use

Detects an executable initiating a network connection to "ngrok" tunneling domains.

## Variations

_(No variations are documented for this entry.)_
