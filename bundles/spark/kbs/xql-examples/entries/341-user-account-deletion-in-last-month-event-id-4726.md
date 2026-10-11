---
id: XQL-341-ea9bed8a
title: User Account Deletion in Last Month (Event ID 4726)
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

# User Account Deletion in Last Month (Event ID 4726)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =30D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter target_username = event_data -> TargetUserName,user_domain = event_data -> TargetDomainName,IpAddress = event_data -> IpAddress
| filter event_id_num = 4726
| fields _time, target_username, user_domain, IpAddress,*
| sort desc _time
```

## When to use

Lists the user accounts that were deleted in the last month based on event ID 4726, and includes user and IP details

## Variations

_(No variations are documented for this entry.)_
