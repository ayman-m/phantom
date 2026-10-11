---
id: XQL-254-12c1b07c
title: IIS running discovery commands
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
---

# IIS running discovery commands

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // look at xdr data
|filter lowercase(causality_actor_process_image_name) = "w3wp.exe"  // filter IIS
|filter lowercase(action_process_image_name) in ("net.exe", "quser.exe", "certutil.exe", "arp.exe", "hostname.exe", "whoami.exe", "netstat.exe", "ping.exe", "ipconfig.exe", "wmic.exe", "del.exe", "cmd.exe", "powershell.exe") // look for discovery commands
|fields agent_hostname, agent_version, actor_effective_username , causality_actor_process_image_name,  causality_actor_process_command_line  , actor_process_image_name, actor_process_command_line, action_process_image_name, action_process_image_command_line
```

## When to use

Displays possible webshell abuse by attackers

## Variations

_(No variations are documented for this entry.)_
