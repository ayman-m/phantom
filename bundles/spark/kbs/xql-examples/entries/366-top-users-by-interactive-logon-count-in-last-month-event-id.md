---
id: XQL-366-e26a83ad
title: Top Users by Interactive Logon Count in Last Month (Event ID 4624)
category: investigation
dataset: microsoft_windows_raw
tags:
  - config
  - alter
  - filter
  - comp
  - sort
  - limit
  - microsoft_windows_raw
  - source:dataset
---

# Top Users by Interactive Logon Count in Last Month (Event ID 4624)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe = 30D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter user_name = event_data -> TargetUserName,logon_type = event_data -> LogonType
| filter event_id_num = 4624 and logon_type = "2"
| comp count() as interactive_logon_count by user_name
| sort desc interactive_logon_count
| limit 10
```

## When to use

Lists the users who used interactive logon types the most in the last month based on event ID 4624, and filtered by logon type 2, the interactive logon

## Variations

_(No variations are documented for this entry.)_
