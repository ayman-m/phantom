---
id: XQL-762-f7c545c2
title: Top file-write directories (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - alter
  - comp
  - sort
  - limit
  - xdr_data
  - file
---

# Top file-write directories (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.FILE and action_file_path != null
| alter dir = arrayindex(regextract(action_file_path, "^(.+)\\\\[^\\\\]+$"), 0)
| comp count() as writes by dir
| sort desc writes
| limit 10
```

## When to use

Directory-level file-write distribution. Reveals which paths are most-written-to in the tenant — useful for tuning detections (exclude noisy paths) + spotting unusual destinations.

## Variations

_(No variations are documented for this entry.)_
