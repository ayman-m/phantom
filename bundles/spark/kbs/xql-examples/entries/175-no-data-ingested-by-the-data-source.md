---
id: XQL-175-27896b11
title: No data ingested by the data source
category: general
dataset: metrics_view
tags:
  - comp
  - filter
  - metrics_view
  - source:preset
---

# No data ingested by the data source

**Dataset**: `metrics_view`

```sql
//No data ingested by the data source within a time frame
preset = metrics_view  
| comp sum(total_event_count) as total_event_count_sum by _collector_id, _collector_ip, _collector_name, _collector_type , _final_reporting_device_ip ,_final_reporting_device_name , _broker_device_id ,_vendor , _product 
| filter total_event_count_sum = 0
```

## When to use

No data ingested by the data source. Queries the `metrics_view` preset, filtered on `total_event_count_sum = 0`. Uses stages: `comp`, `filter`.

## Variations

_(No variations are documented for this entry.)_
