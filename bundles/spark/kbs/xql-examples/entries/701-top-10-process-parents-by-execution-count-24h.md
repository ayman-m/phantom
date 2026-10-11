---
id: XQL-701-48dce770
title: Top 10 process parents by execution count (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - sort
  - limit
  - xdr_data
  - process
---

# Top 10 process parents by execution count (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| comp count() as cnt by actor_process_image_name
| sort desc cnt
| limit 10
```

## When to use

Surface which processes spawn the most children. Useful for understanding normal process trees + spotting unusual high-spawn parents (e.g. compromised explorer.exe).

## Variations

_(No variations are documented for this entry.)_
