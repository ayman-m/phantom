---
id: XQL-760-f33b855d
title: Files written with double extension (24h, T1036.007)
category: detection
dataset: xdr_data
tags:
  - filter
  - fields
  - sort
  - limit
  - xdr_data
  - file
  - T1036.007
---

# Files written with double extension (24h, T1036.007)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.FILE
| filter action_file_path ~= "(?i)\\.(pdf|doc|xls|jpg|png|txt|zip)\\.(exe|scr|bat|cmd|com|lnk)$"
| fields _time, agent_hostname, action_process_image_name, action_file_path
| sort desc _time
| limit 10
```

## When to use

Files written with double-extension naming (e.g. report.pdf.exe). MITRE T1036.007 — common social-engineering trick that exploits Windows's hide-extension default.

## Variations

_(No variations are documented for this entry.)_
