---
id: XQL-702-edf4c6e4
title: Process pairs — parent → child execution chains (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - sort
  - limit
  - xdr_data
  - process
---

# Process pairs — parent → child execution chains (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| comp count() as cnt by actor_process_image_name, action_process_image_name
| sort desc cnt
| limit 10
```

## When to use

Identifies the most common parent → child process execution pairs. Foundational pattern for behavior-baseline analytics + lateral movement detection (rare pairs = candidates).

## Variations

_(No variations are documented for this entry.)_
