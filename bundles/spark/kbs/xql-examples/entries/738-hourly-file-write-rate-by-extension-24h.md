---
id: XQL-738-861d6303
title: Hourly file-write rate by extension (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - bin
  - comp
  - sort
  - limit
  - xdr_data
  - file
---

# Hourly file-write rate by extension (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.FILE
| bin _time span = 1h
| comp count() as writes by _time, action_file_extension
| sort desc _time
| limit 10
```

## When to use

Time-bucketed file-write volume by extension. Reveals daily patterns + sudden bursts (ransomware encryption events drop many similar files).

## Variations

_(No variations are documented for this entry.)_
