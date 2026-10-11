---
id: XQL-709-7c7c9a43
title: Top files written by process (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - sort
  - limit
  - xdr_data
  - file
---

# Top files written by process (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.FILE
| comp count() as writes by actor_process_image_name, action_file_extension
| sort desc writes
| limit 10
```

## When to use

Which processes write the most files, by extension. Useful for understanding normal-state writers (system processes) so you can spot anomalies (e.g. unexpected process writing .exe files).

## Variations

_(No variations are documented for this entry.)_
