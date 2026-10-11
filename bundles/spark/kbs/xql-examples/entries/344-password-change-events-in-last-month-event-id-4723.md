---
id: XQL-344-b3a39e4e
title: Password Change Events in Last Month (Event ID 4723)
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

# Password Change Events in Last Month (Event ID 4723)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =30D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter target_username = event_data -> TargetUserName,user_domain = event_data -> TargetDomainName,IpAddress = event_data -> IpAddress
| filter event_id_num = 4720
| fields _time, target_username, user_domain, IpAddress,*
| sort desc _time
```

## When to use

Lists the user accounts that had password changes in the last month based on event ID 4723, and includes user and domain information

## Variations

_(No variations are documented for this entry.)_
