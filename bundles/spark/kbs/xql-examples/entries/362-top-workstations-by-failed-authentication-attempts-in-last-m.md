---
id: XQL-362-18b86f43
title: Top Workstations by Failed Authentication Attempts in Last Month (Event ID 4771)
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

# Top Workstations by Failed Authentication Attempts in Last Month (Event ID 4771)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =30D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter workstation_name = event_data -> WorkstationName
| filter event_id_num = 4771
| comp count() as failed_attempts by workstation_name
| sort desc failed_attempts
| limit 10
```

## When to use

Lists the top workstations with the most failed authentication attempts in the last month based on event ID 4771, and includes the count of failed attempts by workstation

## Variations

_(No variations are documented for this entry.)_
