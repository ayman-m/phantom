---
id: XQL-343-0b721b22
title: File Deletion Events in Last 7 Days (Event ID 4660)
category: investigation
dataset: microsoft_windows_raw
tags:
  - config
  - alter
  - filter
  - fields
  - sort
  - microsoft_windows_raw
  - source:dataset
---

# File Deletion Events in Last 7 Days (Event ID 4660)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =7D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter target_username = event_data -> TargetUserName,file_path = arrayindex(regextract(message, "Path:\s*(.+?\\\w+);?\s+\w+\s+\w+"), 0)
| filter event_id_num = 4660
| fields _time, target_username, file_path,*
| sort desc _time
```

## When to use

Lists the files that were deleted in the last 7 days based on event ID 4660, and includes the user and file path

## Variations

_(No variations are documented for this entry.)_
