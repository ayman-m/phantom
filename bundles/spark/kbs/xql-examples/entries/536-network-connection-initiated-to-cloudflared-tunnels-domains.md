---
id: XQL-536-92773fef
title: Network Connection Initiated To Cloudflared Tunnels Domains
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
  - Network
  - IOC
---

# Network Connection Initiated To Cloudflared Tunnels Domains

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = 2 and event_sub_type in (2,5,8,11)
| filter (dst_agent_hostname ~= ".*.v2.argotunnel.com" OR  dst_agent_hostname ~= ".*protocol-v2.argotunnel.com" OR  dst_agent_hostname ~= ".*trycloudflare.com" OR  dst_agent_hostname ~= ".*update.argotunnel.com")
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_local_port, action_remote_port, dst_agent_hostname, action_local_ip, action_remote_ip, actor_process_image_command_line, action_network_dpi_fields
```

## When to use

Detects network connections to Cloudflared tunnels domains initiated by a process on the system.

## Variations

_(No variations are documented for this entry.)_
