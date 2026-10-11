---
id: XQL-360-31022668
title: Top Error Codes for Failed Logins (Event ID 4625)
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

# Top Error Codes for Failed Logins (Event ID 4625)

**Dataset**: `microsoft_windows_raw`

```sql
dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter error_code = coalesce(event_data ->error, arrayindex(regextract(message, "Failure\sReason\:\t\t(.*)\n"), 0))
| filter event_id_num = 4625
| comp count() as occurrence_count by error_code
| sort desc occurrence_count
| limit 10
```

## When to use

Lists the most common error codes for failed login attempts based on event ID 4625, which are grouped by error code and includes a count

## Variations

_(No variations are documented for this entry.)_
