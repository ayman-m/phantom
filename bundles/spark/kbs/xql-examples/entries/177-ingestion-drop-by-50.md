---
id: XQL-177-c0f52370
title: Ingestion drop by 50%
category: general
dataset: metrics_view
tags:
  - alter
  - comp
  - join
  - filter
  - metrics_view
  - source:preset
---

# Ingestion drop by 50%

**Dataset**: `metrics_view`

```sql
//Ingestion spike/drop monitoring drop by 50%
preset = metrics_view 
| alter unique_id = concat(_collector_id, _collector_ip, _collector_name, _collector_type , _final_reporting_device_ip ,_final_reporting_device_name , _broker_device_id ,_vendor , _product )
| comp avg(total_event_rate) as total_event_rate_avg by unique_id //, _collector_id, _collector_ip, _collector_name, _collector_type , _final_reporting_device_ip ,_final_reporting_device_name , _broker_device_id ,_vendor , _product
| join conflict_strategy = both  (
    preset = metrics_view |filter timestamp_diff(current_time(), _time ,"minute") <= 10
    | alter unique_id = concat(_collector_id, _collector_ip, _collector_name, _collector_type , _final_reporting_device_ip ,_final_reporting_device_name , _broker_device_id ,_vendor , _product )
    | comp latest(total_event_rate) as total_event_rate, latest(_time) as _time by unique_id ) as last_ten_m last_ten_m.unique_id = unique_id 
| filter total_event_rate < multiply(total_event_rate_avg, 0.5)
```

## When to use

Ingestion drop by 50%. Queries the `metrics_view` preset, filtered on `timestamp_diff(current_time(), _time ,"minute") <= 10`. Uses stages: `alter`, `comp`, `join`, `filter`.

## Variations

_(No variations are documented for this entry.)_
