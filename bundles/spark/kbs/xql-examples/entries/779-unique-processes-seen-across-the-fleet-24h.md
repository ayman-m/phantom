---
id: XQL-779-c4da5eda
title: Unique processes seen across the fleet (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - dedup
  - fields
  - sort
  - limit
  - xdr_data
---

# Unique processes seen across the fleet (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| dedup action_process_image_name
| fields action_process_image_name
| sort asc action_process_image_name
| limit 10
```

## When to use

Fleet-wide process whitelist candidate set — every unique process name seen. The first 10 alphabetically. Useful for building an allowlist starter.

## Variations

_(No variations are documented for this entry.)_
