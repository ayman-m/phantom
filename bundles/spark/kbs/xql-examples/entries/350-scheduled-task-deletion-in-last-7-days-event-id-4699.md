---
id: XQL-350-0cf03e48
title: Scheduled Task Deletion in Last 7 Days (Event ID 4699)
category: investigation
dataset: microsoft_windows_raw
tags:
  - config
  - alter
  - filter
  - fields
  - sort
  - microsoft_windows_raw
  - source:dataset
---

# Scheduled Task Deletion in Last 7 Days (Event ID 4699)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =7D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter task_name = arrayindex(regextract(message, "Task Name:\s*(.+?)\s+"), 0),target_username = event_data -> TargetUserName,IpAddress = event_data -> IpAddress
| filter event_id_num = 4699
| fields _time, task_name, target_username, IpAddress,*
| sort desc _time
```

## When to use

Lists the scheduled tasks deleted in the last 7 days based on event ID 4699, and includes task and user details

## Variations

_(No variations are documented for this entry.)_
