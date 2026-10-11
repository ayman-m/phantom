---
id: XQL-351-1af067f3
title: System Shutdown Events (Event ID 1074)
category: investigation
dataset: microsoft_windows_raw
tags:
  - alter
  - filter
  - fields
  - sort
  - microsoft_windows_raw
  - source:dataset
---

# System Shutdown Events (Event ID 1074)

**Dataset**: `microsoft_windows_raw`

```sql
dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter target_username = event_data -> TargetUserName,shutdown_reason = arrayindex(regextract(message, "reason\:\s+(.*?)\n"), 0)
| filter event_id_num = 1074
| fields _time, target_username, shutdown_reason, message,*
| sort desc _time
```

## When to use

Lists details of system shutdown events based on event ID 1074, and includes who performed the shutdown and the reason

## Variations

_(No variations are documented for this entry.)_
