---
id: XQL-136-7ec29702
title: Cortex XSIAM JAMF Monitoring - Custom XQL Widget
category: investigation
dataset: jamf_pro_raw
tags:
  - bin
  - comp
  - filter
  - view
---

# Cortex XSIAM JAMF Monitoring - Custom XQL Widget

**Dataset**: `jamf_pro_raw`

```sql
dataset = jamf_pro_raw
| filter device_udid != null
| bin _time span = 10m
| comp count(device_udid) as number_devices by _time
| view graph type = line xaxis = _time yaxis = number_devices
```

## When to use

Cortex XSIAM JAMF Monitoring - Custom XQL Widget. Queries the `jamf_pro_raw` dataset directly, filtered on `device_udid != null`. Uses stages: `filter`, `bin`, `comp`, `view`.

## Variations

_(No variations are documented for this entry.)_
