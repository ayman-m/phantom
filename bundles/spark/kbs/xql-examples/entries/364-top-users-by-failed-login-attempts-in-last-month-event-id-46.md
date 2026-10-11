---
id: XQL-364-b755c829
title: Top Users by Failed Login Attempts in Last Month (Event ID 4625)
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

# Top Users by Failed Login Attempts in Last Month (Event ID 4625)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =30D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter target_username = event_data -> TargetUserName
| filter event_id_num = 4625
| comp count() as failed_attempts by target_username
| sort desc failed_attempts
| limit 10
```

## When to use

Lists the users with the highest number of failed login attempts in the last month based on event ID 4625

## Variations

_(No variations are documented for this entry.)_
