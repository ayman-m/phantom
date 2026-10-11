---
id: XQL-835-d67342cb
title: Round-to-100 normalized command-line lengths (24h, round)
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
  - round
  - math
---

# Round-to-100 normalized command-line lengths (24h, round)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START and action_process_image_command_line != null
| alter cmd_len = len(action_process_image_command_line)
| alter len_bucket = multiply(round(divide(cmd_len, 100)), 100)
| comp count() as cnt by len_bucket
| sort desc cnt
| limit 10
```

## When to use

Process command-line lengths bucketed to nearest 100 chars. `round + divide + multiply` chains together for clean rounding. Histogram pattern adaptable to other numeric fields.

## Variations

_(No variations are documented for this entry.)_
