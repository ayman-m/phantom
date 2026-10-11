---
id: XQL-356-c760502b
title: Top Users by Account Lockouts in Last Month (Event ID 4740)
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

# Top Users by Account Lockouts in Last Month (Event ID 4740)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =30D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter target_username = event_data -> TargetUserName
| filter event_id_num = 4740
| comp count() as lockout_count by target_username
| sort desc lockout_count
| limit 10
```

## When to use

Lists the top users with the most account lockouts in the last month based on event ID 4740

## Variations

_(No variations are documented for this entry.)_
