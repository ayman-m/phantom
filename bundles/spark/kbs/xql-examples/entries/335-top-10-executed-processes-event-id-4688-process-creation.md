---
id: XQL-335-712669f5
title: Top 10 Executed Processes (Event ID 4688 - Process Creation)
category: investigation
dataset: microsoft_windows_raw
tags:
  - alter
  - filter
  - comp
  - sort
  - limit
  - microsoft_windows_raw
  - source:dataset
---

# Top 10 Executed Processes (Event ID 4688 - Process Creation)

**Dataset**: `microsoft_windows_raw`

```sql
dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter process_name_format = coalesce(event_data -> ProcessName, arrayindex(regextract(message, "Process Name:\s*(\S+)"), 0))
| filter event_id_num = 4688
| comp count(process_name_format) as process_count by process_name_format
| sort desc process_count
| limit 10
```

## When to use

Lists the top 10 most frequently executed processes based on event ID 4688 for the process creation events

## Variations

_(No variations are documented for this entry.)_
