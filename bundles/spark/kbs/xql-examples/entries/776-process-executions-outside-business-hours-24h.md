---
id: XQL-776-2dfb9739
title: Process executions outside business hours (24h)
category: detection
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

# Process executions outside business hours (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| alter hour_of_day = format_timestamp("%H", _time)
| filter hour_of_day in ("00", "01", "02", "03", "04", "05", "22", "23")
| comp count() as cnt by agent_hostname, action_process_image_name, actor_effective_username
| sort desc cnt
| limit 10
```

## When to use

Process executions during off-hours (22:00-05:00). Uses `format_timestamp` to extract the hour. After-hours activity by interactive users is a common compromise indicator.

## Variations

_(No variations are documented for this entry.)_
