---
id: XQL-763-c4b27d2d
title: Outbound to RFC1918-only ports from public destinations (24h)
category: detection
dataset: xdr_data
tags:
  - filter
  - fields
  - sort
  - limit
  - xdr_data
  - network
  - incidr
---

# Outbound to RFC1918-only ports from public destinations (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK and action_remote_port in (445, 139, 135, 3389)
| filter not incidr(action_remote_ip, "10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8")
| fields _time, agent_hostname, action_remote_ip, action_remote_port
| sort desc _time
| limit 10
```

## When to use

Connections to Windows-internal ports (SMB 445, NetBIOS 139, RPC 135, RDP 3389) on PUBLIC IPs. Highly suspicious — these ports should never traverse the internet. Misconfiguration or attacker activity.

## Variations

_(No variations are documented for this entry.)_
