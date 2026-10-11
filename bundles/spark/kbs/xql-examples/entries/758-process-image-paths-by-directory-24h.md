---
id: XQL-758-f5ff094b
title: Process image paths by directory (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - alter
  - comp
  - sort
  - limit
  - xdr_data
  - process
  - regextract
---

# Process image paths by directory (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START and action_process_image_path != null
| alter dir = arrayindex(regextract(action_process_image_path, "^(.+)\\\\[^\\\\]+$"), 0)
| comp count() as cnt by dir
| sort desc cnt
| limit 10
```

## When to use

Aggregates process executions by directory. Useful for understanding which install locations dominate + spotting unusual directories. Uses regextract to drop the basename.

## Variations

_(No variations are documented for this entry.)_
