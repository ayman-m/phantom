---
id: XQL-342-0ac0694e
title: Audit Policy Changes in Last 7 Days (Event ID 4719)
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

# Audit Policy Changes in Last 7 Days (Event ID 4719)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =7D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter target_username = event_data -> TargetUserName,IpAddress = event_data -> IpAddress
| filter event_id_num = 4719
| fields _time, target_username, IpAddress,*
| sort desc _time
```

## When to use

Lists any audit policy changes in the last 7 days based on event ID 4719, and includes user and IP address information

## Variations

_(No variations are documented for this entry.)_
