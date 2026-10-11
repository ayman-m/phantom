---
id: XQL-115-b0c17553
title: 1000 eyes - Custom XQL Widget
category: investigation
dataset: cisco_1000_raw
tags:
  - alter
  - comp
  - fields
  - filter
---

# 1000 eyes - Custom XQL Widget

**Dataset**: `cisco_1000_raw`

```sql
dataset = cisco_1000_raw
| filter alert_id != null
// | alter details = arraystring(details -> [], ",")
| comp min(_time) as _time ,count() as c , values(eventId)as event_ids , values(cleared_time) as cleared_time, values(devices_names) as devices_names, values(details) as details by alert_id, testId, signature, test_type , alert_type, triggered_time, itsiDrilldownURI, vendor_severity, test_name  addrawdata = true
| filter c < 2 and cleared_time = null
| alter details = arraymerge(details )
| alter devices_names = arraymerge(devices_names)
| fields vendor_severity ,alert*, test*, signature  , devices_names, details , cleared_time
```

## When to use

1000 eyes - Custom XQL Widget. Queries the `cisco_1000_raw` dataset directly, filtered on `alert_id != null`. Uses stages: `filter`, `alter`, `comp`, `fields`.

## Variations

_(No variations are documented for this entry.)_
