---
id: XQL-023-67e6c8f9
title: Health - Strong deviation in ingestion rate using Z score
category: investigation
tags:
  - alter
  - bin
  - comp
  - filter
  - join
---

# Health - Strong deviation in ingestion rate using Z score

**Dataset**: `(none)`

```sql
preset = metrics_view
|filter last_seen > to_timestamp(1754146800000, "MILLIS") and timestamp_diff(current_time(), _time ,"minute") >= 6
| alter unique_id = concat(_collector_id, _collector_ip, _collector_name, _collector_type, _collector_internal_ip_address, _final_reporting_device_ip, _final_reporting_device_name, _reporting_device_name, _collector_hostname, _broker_device_id, _device_id, _log_type, _vendor, _product)
| alter t = _time
| bin t span = 1h
| comp sum(total_event_count) as total_event_count by unique_id, t
| comp avg(total_event_count) as total_event_count_avg , var(total_event_count) as total_event_count_var by unique_id addrawdata = true as raw_stat //, _collector_id, _collector_ip, _collector_name, _collector_type , _final_reporting_device_ip ,_final_reporting_device_name , _broker_device_id ,_vendor , _product
| join conflict_strategy = both  (
    preset = metrics_view |filter timestamp_diff(current_time(), _time ,"minute") >= 6 and timestamp_diff(current_time(), _time ,"minute") <= 65
    | alter unique_id = concat(_collector_id, _collector_ip, _collector_name, _collector_type, _collector_internal_ip_address, _final_reporting_device_ip, _final_reporting_device_name, _reporting_device_name, _collector_hostname, _broker_device_id, _device_id, _log_type, _vendor, _product)
    | alter t = _time
    | bin t span = 1h
    | comp sum(total_event_count) as total_event_count, values(_time) as v by unique_id, t addrawdata = true as jonined_raw
       ) as last_ten_m last_ten_m.unique_id = unique_id
| alter distance_to_average  =  subtract(total_event_count_avg, total_event_count)
| alter total_event_count_std = pow(total_event_count_var, 0.5)
| alter distance_to_average = if(distance_to_average <0 , multiply(distance_to_average , -1), distance_to_average )
| alter anom = divide(distance_to_average ,total_event_count_std)
| filter anom > 3
```

## When to use

Health - Strong deviation in ingestion rate using Z score. Queries the `(none)` preset, filtered on `last_seen > to_timestamp(1754146800000, "MILLIS") and timestamp_diff(current_time(), _time ,"minute") >= 6`. Uses stages: `filter`, `alter`, `bin`, `comp`, `join`.

## Variations

_(No variations are documented for this entry.)_
