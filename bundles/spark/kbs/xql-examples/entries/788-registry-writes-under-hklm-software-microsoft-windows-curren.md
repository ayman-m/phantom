---
id: XQL-788-23413cde
title: Registry writes under HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run (24h)
category: detection
dataset: xdr_data
tags:
  - filter
  - fields
  - sort
  - limit
  - xdr_data
  - registry
  - T1547
---

# Registry writes under HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.REGISTRY
| filter action_registry_key_name contains "\\CurrentVersion\\Run"
| fields _time, agent_hostname, actor_process_image_name, action_registry_key_name, action_registry_value_name, action_registry_data
| sort desc _time
| limit 10
```

## When to use

Specific persistence-via-Run-key pattern. Returns the data being written for IOC extraction (path of persistent payload).

## Variations

_(No variations are documented for this entry.)_
