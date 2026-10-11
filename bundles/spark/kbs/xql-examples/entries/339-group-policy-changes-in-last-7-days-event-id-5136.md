---
id: XQL-339-1cc8eae2
title: Group Policy Changes in Last 7 Days (Event ID 5136)
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

# Group Policy Changes in Last 7 Days (Event ID 5136)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =7D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter target_username = event_data -> TargetUserName,event_name = arrayindex(regextract(message, "([^\.]+)\."), 0),IpAddress = event_data -> IpAddress
| filter event_id_num = 5136
| fields _time, target_username, event_name, IpAddress,*
| sort desc _time
```

## When to use

Details any changes made to Group Policy settings in the last 7 days based on event ID 5136

## Variations

_(No variations are documented for this entry.)_
