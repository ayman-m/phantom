---
id: XQL-352-8944ce12
title: Top 10 Most Active User Accounts in Last Month (Event ID 4624)
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

# Top 10 Most Active User Accounts in Last Month (Event ID 4624)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =30D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter target_username = event_data -> TargetUserName
| filter event_id_num = 4624
| comp count() as login_count by target_username
| sort desc login_count
| limit 10
```

## When to use

Lists the top 10 user accounts with the highest number of logins in the last month based on event ID 4624

## Variations

_(No variations are documented for this entry.)_
