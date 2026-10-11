---
id: XQL-007-94cde9af
title: IoT Security - New Raspberry Device Found
category: investigation
dataset: panw_iot_security_devices_raw
tags:
  - alter
  - dedup
  - filter
---

# IoT Security - New Raspberry Device Found

**Dataset**: `panw_iot_security_devices_raw`

```sql
dataset = panw_iot_security_devices_raw
| filter profile contains "Raspberry Pi Device"
| alter duration_time = timestamp_diff(_insert_time,first_seen_date,"MINUTE")
| filter duration_time <= 30 and duration_time  >= 0
//| dedup mac_address
```

## When to use

IoT Security - New Raspberry Device Found. Queries the `panw_iot_security_devices_raw` dataset directly, filtered on `profile contains "Raspberry Pi Device"`. Uses stages: `filter`, `alter`, `dedup`.

## Variations

_(No variations are documented for this entry.)_
