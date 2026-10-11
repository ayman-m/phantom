---
id: XQL-782-bbc60977
title: Process names split by hyphen — first segment (24h)
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
  - split
---

# Process names split by hyphen — first segment (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START and action_process_image_name != null
| alter prefix = arrayindex(split(action_process_image_name, "-"), 0)
| comp count() as cnt by prefix
| sort desc cnt
| limit 10
```

## When to use

Splits process names on hyphen + aggregates by the first segment. Useful for vendor-prefix aggregation (e.g. `chrome-helper-*` all become `chrome`).

## Variations

_(No variations are documented for this entry.)_
