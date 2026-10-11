---
id: XQL-317-1e056cc8
title: Hosts with Log in Events on Popular Ports
category: investigation
dataset: xdr_login_events
tags:
  - preset
  - filter
  - fields
  - xdr_login_events
  - source:preset
---

# Hosts with Log in Events on Popular Ports

**Dataset**: `xdr_login_events`

```sql
preset = xdr_login_events
| filter agent_hostname in($host)
| filter (action_local_port in (22, 23, 445, 3389))
| fields agent_hostname, agent_ip_addresses, actor_effective_username, action_local_ip, action_local_port, action_remote_ip, action_remote_port,*
```

## When to use

Lists the hosts that have recorded log in events on commonly targeted ports, such as 22 (SSH), 23 (Telnet), 445 (SMB), and 3389 (RDP), which could be indicators of brute force attacks or unauthorized access attempts

## Variations

_(No variations are documented for this entry.)_
