---
id: XQL-334-22b03fd3
title: Successful Log in Attempts in Last 24 Hours (Event ID 4624)
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

# Successful Log in Attempts in Last 24 Hours (Event ID 4624)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =24H
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter IpAddress = event_data -> IpAddress,
        target_username = event_data -> TargetUserName
| filter event_id_num = 4624
| fields _time, target_username, IpAddress,*
| sort desc _time
```

## When to use

Lists all successful log in attempts in the last 24 hours based on event ID 4624 and includes the relevant details

## Variations

_(No variations are documented for this entry.)_
