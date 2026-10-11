---
id: XQL-358-83688b19
title: Top IPs by Firewall Rule Changes (Event ID 4950)
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

# Top IPs by Firewall Rule Changes (Event ID 4950)

**Dataset**: `microsoft_windows_raw`

```sql
dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter IpAddress = event_data -> IpAddress
| filter event_id_num = 4950
| comp count() as firewall_changes by IpAddress
| sort desc firewall_changes
| limit 10
```

## When to use

Lists the top IP addresses involved in firewall rule changes in the last month based on event ID 4950

## Variations

_(No variations are documented for this entry.)_
