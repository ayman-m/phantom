---
id: XQL-215-be817eaa
title: Machines that accepted VNC connections
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
---

# Machines that accepted VNC connections

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.NETWORK and event_sub_type = ENUM.NETWORK_STREAM_ACCEPT and action_local_port in (5900,5999) // Looking for network connection related to VNC, over ports 5900-5999
 | fields event_type, agent_hostname as Hostname, action_local_ip as Local_IP, action_remote_ip as Remote_IP, action_external_hostname as Remote_Host, action_local_port as Local_Port, actor_process_image_name as Process_Getting_Connection // Selecting the relevant fields
```

## When to use

Display all machines that have accepted incoming VNC connections (meaning remote device connects to it over VNC, using port 5900-5999)

## Variations

_(No variations are documented for this entry.)_
