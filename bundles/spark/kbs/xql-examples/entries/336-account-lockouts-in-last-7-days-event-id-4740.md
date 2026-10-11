---
id: XQL-336-248b3428
title: Account Lockouts in Last 7 Days (Event ID 4740)
category: investigation
dataset: microsoft_windows_raw
tags:
  - config
  - alter
  - filter
  - fields
  - microsoft_windows_raw
  - source:dataset
---

# Account Lockouts in Last 7 Days (Event ID 4740)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =7D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter IpAddress = event_data -> IpAddress,
        target_username = event_data -> TargetUserName
| filter event_id_num = 4740
| fields _time, target_username, IpAddress,*
```

## When to use

Lists the accounts that have been locked out in the past 7 days based on event ID 4740

## Variations

_(No variations are documented for this entry.)_
