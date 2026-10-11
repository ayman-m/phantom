---
id: XQL-716-a57dc0aa
title: Persistence via autorun-key registry writes (24h, T1547)
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

# Persistence via autorun-key registry writes (24h, T1547)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.REGISTRY
| filter action_registry_key_name contains "\\Run" or action_registry_key_name contains "\\RunOnce" or action_registry_key_name contains "\\Image File Execution Options"
| fields _time, agent_hostname, actor_process_image_name, action_registry_key_name, action_registry_value_name
| sort desc _time
| limit 10
```

## When to use

MITRE T1547 — Boot or Logon Autostart Execution. Captures writes to the canonical autorun registry locations + Image File Execution Options (a debugger-hijack persistence vector).

## Variations

_(No variations are documented for this entry.)_
