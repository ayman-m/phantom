---
id: XQL-333-828bfdd9
title: Failed Log in Attempts by Source IP (Event ID 4625)
category: investigation
dataset: microsoft_windows_raw
tags:
  - alter
  - filter
  - comp
  - microsoft_windows_raw
  - source:dataset
---

# Failed Log in Attempts by Source IP (Event ID 4625)

**Dataset**: `microsoft_windows_raw`

```sql
dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter IpAddress = event_data -> IpAddress,
        target_username = event_data -> TargetUserName
| filter event_id_num = 4625
| comp count(target_username) as failed_login_count by IpAddress
```

## When to use

Tracks the number of failed log in attempts (event ID 4625) and groups them by the source IP address

## Variations

_(No variations are documented for this entry.)_
