---
id: XQL-079-d1389b8f
title: Daily Check Report - Last Ingestion by Device, Collector Type
category: investigation
tags:
  - alter
  - dedup
  - fields
  - filter
  - sort
---

# Daily Check Report - Last Ingestion by Device, Collector Type

**Dataset**: `(none)`

```sql
preset = metrics_view
| filter _collector_type in ("*")
| alter 90th_percentile_latency_seconds = round(data_freshness_ninetieth_percentile), ven_prod = concat(_vendor, " ", _product), device = trim(concat(_reporting_device_name, " ", " " , _reporting_device_ip, " ", _final_reporting_device_name), " "), source = trim(concat(_broker_device_name, " ", _collector_name), " "), tz_corrected = parse_timestamp("%Y-%m-%d %H:%M:%S+00", to_string(last_seen), "+7:00")
| alter last_received = to_string(tz_corrected), last_seen_ = to_string(last_seen), latency_in_seconds = to_string(90th_percentile_latency_seconds)
| fields ven_prod, device, last_received as last_received_local_time, source, _collector_type, latency_in_seconds
| dedup device
| filter not device contains "ASIA"
| sort asc _vendor
```

## When to use

Daily Check Report - Last Ingestion by Device, Collector Type. Queries the `(none)` preset, filtered on `_collector_type in ("*")`. Uses stages: `filter`, `alter`, `fields`, `dedup`, `sort`.

## Variations

_(No variations are documented for this entry.)_
