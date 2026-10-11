---
id: XQL-363-989cd6bd
title: Top IP Addresses by Logon Failures in Last Month (Event ID 4625)
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

# Top IP Addresses by Logon Failures in Last Month (Event ID 4625)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =30D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter ip_address = event_data -> IpAddress
| filter event_id_num = 4625
| comp count() as failed_attempts by ip_address
| sort desc failed_attempts
| limit 10
```

## When to use

Lists the IP addresses with the highest number of logon failures in the last month based on event ID 4625

## Variations

_(No variations are documented for this entry.)_
