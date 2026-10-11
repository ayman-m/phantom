---
id: XQL-755-4089d525
title: Suspicious Office-app child processes (24h, T1566.001)
category: detection
dataset: xdr_data
tags:
  - filter
  - fields
  - sort
  - limit
  - xdr_data
  - process
  - T1566.001
---

# Suspicious Office-app child processes (24h, T1566.001)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| filter lowercase(actor_process_image_name) in ("winword.exe", "excel.exe", "powerpnt.exe", "outlook.exe")
| filter lowercase(action_process_image_name) in ("cmd.exe", "powershell.exe", "wscript.exe", "cscript.exe", "mshta.exe", "rundll32.exe")
| fields _time, agent_hostname, actor_process_image_name, action_process_image_name, action_process_image_command_line
| sort desc _time
| limit 10
```

## When to use

Office applications spawning script hosts/cmd — MITRE T1566.001 (Spearphishing Attachment). One of the highest-fidelity detection patterns for macro-based attacks.

## Variations

_(No variations are documented for this entry.)_
