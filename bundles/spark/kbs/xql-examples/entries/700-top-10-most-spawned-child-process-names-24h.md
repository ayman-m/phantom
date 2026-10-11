---
id: XQL-700-0775d541
title: Top 10 most-spawned child process names (24h)
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

# Top 10 most-spawned child process names (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| comp count() as cnt by action_process_image_name
| sort desc cnt
| limit 10
```

## When to use

Aggregate process-start events by child-process name to find the most-spawned binaries in the tenant. Useful as a baseline before drilling into specific suspicious processes.

## Variations

_(No variations are documented for this entry.)_
