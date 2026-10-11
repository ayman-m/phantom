---
id: XQL-225-eee75f18
title: Machines connecting via RDP using an unusual process
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
---

# Machines connecting via RDP using an unusual process

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.NETWORK and event_sub_type = ENUM.NETWORK_STREAM_CONNECT and action_remote_port = 3389 and actor_process_image_name not in ("mstsc.exe", "Microsoft Remote Desktop")
  // Looking for remote network connection related to RDP that was opened using something other than mstsc.exe
 | fields event_type, agent_hostname as Hostname, action_local_ip as Local_IP, action_remote_ip as Remote_IP, action_external_hostname as Remote_Host, action_local_port as Local_Port, actor_process_image_name as Process_Getting_Connection // Selecting the relevant fields
```

## When to use

Display cases where Windows endpoints connected to another over port 3389 (and 3390) using a process that is not mstsc.exe

## Variations

_(No variations are documented for this entry.)_
