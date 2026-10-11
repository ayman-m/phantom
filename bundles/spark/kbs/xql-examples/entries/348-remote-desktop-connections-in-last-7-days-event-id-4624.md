---
id: XQL-348-5877eca6
title: Remote Desktop Connections in Last 7 Days (Event ID 4624)
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

# Remote Desktop Connections in Last 7 Days (Event ID 4624)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =7D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter target_username = event_data -> TargetUserName,IpAddress = event_data -> IpAddress,logonType = event_data -> LogonType
| filter event_id_num = 4624 and logonType = "10"
| fields _time, target_username, IpAddress, logonType,*
| sort desc _time
```

## When to use

Lists the Remote Desktop Protocol (RDP) connections in the last 7 days based on event ID 4624, and includes user and IP details

## Variations

_(No variations are documented for this entry.)_
