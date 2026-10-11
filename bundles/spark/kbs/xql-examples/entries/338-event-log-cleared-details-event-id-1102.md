---
id: XQL-338-c2dddc09
title: Event Log Cleared Details (Event ID 1102)
category: investigation
dataset: microsoft_windows_raw
tags:
  - alter
  - filter
  - fields
  - microsoft_windows_raw
  - source:dataset
---

# Event Log Cleared Details (Event ID 1102)

**Dataset**: `microsoft_windows_raw`

```sql
dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter IpAddress = event_data -> IpAddress,target_username = event_data -> TargetUserName
| filter event_id_num = 1102
| fields _time, target_username, IpAddress,*
```

## When to use

Lists details about when and by whom the Windows event log was cleared based on event ID 1102

## Variations

_(No variations are documented for this entry.)_
