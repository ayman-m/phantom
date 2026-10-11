---
id: XQL-353-43c825e4
title: Top IPs with Failed Logon Attempts (Event ID 4625)
category: investigation
dataset: microsoft_windows_raw
tags:
  - alter
  - filter
  - comp
  - sort
  - limit
  - microsoft_windows_raw
  - source:dataset
---

# Top IPs with Failed Logon Attempts (Event ID 4625)

**Dataset**: `microsoft_windows_raw`

```sql
dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter IpAddress = event_data -> IpAddress
| filter event_id_num = 4625
| comp count() as failed_attempts by IpAddress
| sort desc failed_attempts
| limit 10
```

## When to use

Lists the IP addresses with the most failed logon attempts based on event ID 4625

## Variations

_(No variations are documented for this entry.)_
