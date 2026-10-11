---
id: XQL-748-5b33884f
title: Unique processes per host (deduped, 24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - dedup
  - fields
  - sort
  - limit
  - xdr_data
  - process
---

# Unique processes per host (deduped, 24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| dedup agent_hostname, action_process_image_name
| fields agent_hostname, action_process_image_name
| sort asc agent_hostname
| limit 10
```

## When to use

DEDUP stage collapses to one row per (host, process). Returns the unique processes seen per host — useful for whitelist generation + process-inventory snapshots.

## Variations

_(No variations are documented for this entry.)_
