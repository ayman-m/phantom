---
id: XQL-359-ed7cc7cd
title: Top Logon Types in Last Month (Event ID 4624)
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

# Top Logon Types in Last Month (Event ID 4624)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =30D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter logon_type = event_data -> LogonType
| filter event_id_num = 4624
| comp count() as logon_count by logon_type
| sort desc logon_count
| limit 10
```

## When to use

Lists the most common logon types in the last month based on event ID 4624, which are grouped by the logon type and includes a count

## Variations

_(No variations are documented for this entry.)_
