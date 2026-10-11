---
id: XQL-365-532deb51
title: Top Services by Activity in Last 7 Days (Event ID 7040 and 7045)
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

# Top Services by Activity in Last 7 Days (Event ID 7040 and 7045)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =7D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter service_name = arrayindex(regextract(message, "Service Name:\s*(.+?)\s+"), 0)
| filter event_id_num in (7040, 7045)
| comp count() as activity_count by service_name
| sort desc activity_count
| limit 10
```

## When to use

Lists the top services by activity in the last 7 days based on event IDs 7040 and 7045, and includes the count of start/stop actions by service

## Variations

_(No variations are documented for this entry.)_
