---
id: XQL-777-222632bb
title: Process activity by day-of-week (7d)
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
  - format_timestamp
---

# Process activity by day-of-week (7d)

**Dataset**: `xdr_data`

```sql
config timeframe = 7d
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| alter dow = format_timestamp("%A", _time)
| comp count() as cnt by dow
| sort desc cnt
| limit 10
```

## When to use

Day-of-week activity distribution. Weekend activity volumes vs weekday are useful for baseline + spotting bursts on unusual days.

## Variations

_(No variations are documented for this entry.)_
