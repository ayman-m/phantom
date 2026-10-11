---
id: XQL-024-1580023f
title: Health - Ingestion is absolute zero
category: investigation
tags:
  - comp
  - filter
---

# Health - Ingestion is absolute zero

**Dataset**: `(none)`

```sql
preset = metrics_view
|filter last_seen > to_timestamp(1754146800000, "MILLIS") //start of reg handoff - 0800,2-AUG
| comp sum(total_event_count) as total_event_count_sum by _collector_id, _collector_ip, _collector_name, _collector_type, _collector_internal_ip_address, _final_reporting_device_ip, _final_reporting_device_name, _reporting_device_name, _collector_hostname, _broker_device_id, _device_id, _log_type, _vendor, _product
| filter total_event_count_sum = 0
```

## When to use

Health - Ingestion is absolute zero. Queries the `(none)` preset, filtered on `last_seen > to_timestamp(1754146800000, "MILLIS") //start of reg handoff - 0800,2-AUG`. Uses stages: `filter`, `comp`.

## Variations

_(No variations are documented for this entry.)_
