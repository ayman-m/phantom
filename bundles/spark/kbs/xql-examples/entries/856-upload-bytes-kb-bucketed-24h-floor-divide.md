---
id: XQL-856-dbee3440
title: Upload bytes KB-bucketed (24h, floor + divide)
category: investigation
dataset: xdr_data
tags:
  - filter
  - alter
  - comp
  - sort
  - limit
  - xdr_data
  - network
  - floor
  - math
---

# Upload bytes KB-bucketed (24h, floor + divide)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK and action_total_upload > 0
| alter kb_bucket = floor(divide(action_total_upload, 1000))
| comp count() as cnt by kb_bucket
| sort desc cnt
| limit 10
```

## When to use

KB-bucketed upload byte distribution. `floor(divide(bytes, 1000))` truncates to KB. Useful for histogram-style upload-size profiling.

## Variations

_(No variations are documented for this entry.)_
