---
id: XQL-337-7147e6a6
title: Process Creation Events (Event ID 4688)
category: investigation
dataset: microsoft_windows_raw
tags:
  - alter
  - filter
  - fields
  - sort
  - microsoft_windows_raw
  - source:dataset
---

# Process Creation Events (Event ID 4688)

**Dataset**: `microsoft_windows_raw`

```sql
dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter process_name_format = coalesce(event_data -> ProcessName, arrayindex(regextract(message, "Process Name:\s*(\S+)"), 0)),
        Command_Path = arrayindex(regextract(message, "Command Path = (.*?)\s{2, }"), 0)
| filter event_id_num = 4688
| fields _time, process_name_format, Command_Path,*
| sort desc _time
```

## When to use

Details the processes that were created on Windows machines based on event ID 4688 and includes the process name and command path

## Variations

_(No variations are documented for this entry.)_
