---
id: XQL-361-58c540f3
title: Top Files Accessed in Last 7 Days (Event ID 4663)
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

# Top Files Accessed in Last 7 Days (Event ID 4663)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =7D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter  file_path = arrayindex(regextract(message , "Path:\s*(.+?\\\w+);?\s+\w+\s+\w+"), 0)
| filter event_id_num = 4663
| comp count() as access_count by file_path
| sort desc access_count
| limit 10
```

## When to use

Lists the top files accessed in the last 7 days based on event ID 4663, and includes the count of access events by file path

## Variations

_(No variations are documented for this entry.)_
