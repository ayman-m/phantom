---
id: XQL-346-19625b55
title: Firewall Rule Changes in the Last Month (Event ID 4950)
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

# Firewall Rule Changes in the Last Month (Event ID 4950)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =30D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter target_username = event_data -> TargetUserName,IpAddress = event_data -> IpAddress
| filter event_id_num = 4950
| fields _time, target_username, IpAddress,*
| sort desc _time
```

## When to use

Tracks changes to any Windows Firewall rules in the last month based on event ID 4950, and includes user and IP details

## Variations

_(No variations are documented for this entry.)_
