---
id: XQL-347-90885a09
title: Security Group Membership Changes in Last Month (Event ID 4728)
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

# Security Group Membership Changes in Last Month (Event ID 4728)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =30D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter target_username = event_data -> TargetUserName,group_name = arrayindex(regextract(message, "Group\sName\:\t\t(.*)\n"), 0),IpAddress = event_data -> IpAddress
| filter event_id_num = 4728
| fields _time, target_username, group_name, IpAddress,*
| sort desc _time
```

## When to use

Lists the changes made to security group memberships in the last month based on event ID 4728, and includes user and group details

## Variations

_(No variations are documented for this entry.)_
