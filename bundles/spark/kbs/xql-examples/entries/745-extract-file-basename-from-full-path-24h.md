---
id: XQL-745-006a5d1e
title: Extract file basename from full path (24h)
category: detection
dataset: xdr_data
tags:
  - filter
  - alter
  - comp
  - sort
  - limit
  - xdr_data
  - file
  - split
---

# Extract file basename from full path (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.FILE
| filter action_file_path != null
| alter basename = arrayindex(split(action_file_path, "\\"), -1)
| comp count() as writes by basename, action_file_extension
| sort desc writes
| limit 10
```

## When to use

Splits the full file path on backslash and takes the last element via `arrayindex(arr, -1)` — gives the file basename without directory. Aggregates writes by basename.

## Variations

_(No variations are documented for this entry.)_
