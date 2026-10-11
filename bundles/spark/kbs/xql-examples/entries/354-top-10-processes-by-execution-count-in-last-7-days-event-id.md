---
id: XQL-354-24cef861
title: Top 10 Processes by Execution Count in Last 7 Days (Event ID 4688)
category: investigation
dataset: microsoft_windows_raw
tags:
  - config
  - alter
  - filter
  - comp
  - sort
  - limit
  - microsoft_windows_raw
  - source:dataset
---

# Top 10 Processes by Execution Count in Last 7 Days (Event ID 4688)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =7D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter process_name_format = coalesce(event_data -> ProcessName, arrayindex(regextract(message, "Process Name:\s*(\S+)"), 0))
| filter event_id_num = 4688
| comp count() as execution_count by process_name_format
| sort desc execution_count
| limit 10
```

## When to use

Lists the top 10 most frequently executed processes in the last 7 days based on event ID 4688 for process creation

## Variations

_(No variations are documented for this entry.)_
