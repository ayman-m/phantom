---
id: XQL-851-7d988f1f
title: Top 3 ranked processes per host (rank, 24h)
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
  - rank
---

# Top 3 ranked processes per host (rank, 24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| comp count() as cnt by agent_hostname, action_process_image_name
| windowcomp rank() by agent_hostname sort desc cnt as proc_rank
| filter proc_rank <= 3
| sort asc agent_hostname, asc proc_rank
| limit 10
```

## When to use

Top-3 processes PER HOST using `rank()`. Handles ties unlike `row_number()`. Canonical top-N-per-group idiom.

## Variations

_(No variations are documented for this entry.)_
