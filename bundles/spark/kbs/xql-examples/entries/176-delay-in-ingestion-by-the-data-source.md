---
id: XQL-176-421740c5
title: Delay in ingestion by the data source
category: general
dataset: metrics_view
tags:
  - comp
  - filter
  - metrics_view
  - source:preset
---

# Delay in ingestion by the data source

**Dataset**: `metrics_view`

```sql
//Delay in ingestion by the data source
preset = metrics_view  
| comp avg(data_freshness_median) as avg_data_freshness_median by _collector_id, _collector_ip, _collector_name, _collector_type , _final_reporting_device_ip ,_final_reporting_device_name , _broker_device_id ,_vendor , _product 
| filter avg_data_freshness_median >600
```

## When to use

Delay in ingestion by the data source. Queries the `metrics_view` preset, filtered on `avg_data_freshness_median >600`. Uses stages: `comp`, `filter`.

## Variations

_(No variations are documented for this entry.)_
