---
id: XQL-751-10f0ba45
title: Network discovery commands (24h, T1018/T1046)
category: detection
dataset: xdr_data
tags:
  - filter
  - fields
  - sort
  - limit
  - xdr_data
  - process
  - T1018
  - T1046
---

# Network discovery commands (24h, T1018/T1046)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| filter lowercase(action_process_image_name) in ("net.exe", "net1.exe", "nltest.exe", "nbtstat.exe", "ping.exe")
| filter action_process_image_command_line ~= "(?i)(view|domain_trusts|/domain|/dclist|workgroup)"
| fields _time, agent_hostname, actor_effective_username, action_process_image_name, action_process_image_command_line
| sort desc _time
| limit 10
```

## When to use

Network/domain discovery activity — MITRE T1018 (Remote System Discovery) and T1046 (Network Service Scanning). Common in early-stage post-compromise reconnaissance.

## Variations

_(No variations are documented for this entry.)_
