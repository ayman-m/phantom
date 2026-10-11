---
id: XQL-345-477ad13b
title: Password Reset Events in the Last Month (Event ID 4724)
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

# Password Reset Events in the Last Month (Event ID 4724)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =30D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter target_username = event_data -> TargetUserName,user_domain = event_data -> TargetDomainName,IpAddress = event_data -> IpAddress
| filter event_id_num = 4724
| fields _time, target_username, user_domain, IpAddress,*
| sort desc _time
```

## When to use

Lists the user accounts that had password resets in the last month based on event ID 4724, and includes user details

## Variations

_(No variations are documented for this entry.)_
