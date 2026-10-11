---
id: XQL-774-ad747036
title: Top-3 processes per host (window-comp top-n pattern, 24h)
category: detection
dataset: xdr_data
tags:
  - filter
  - comp
  - windowcomp
  - sort
  - limit
  - xdr_data
  - process
  - top-n
---

# Top-3 processes per host (window-comp top-n pattern, 24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| comp count() as cnt by agent_hostname, action_process_image_name
| windowcomp row_number() by agent_hostname sort desc cnt as rank
| filter rank <= 3
| sort asc agent_hostname, asc rank
| limit 10
```

## When to use

Top-3 most-spawned processes PER HOST — classic window-function top-N pattern. `row_number()` partitioned by host + sorted by count gives the per-host rank.

## Variations

_(No variations are documented for this entry.)_
