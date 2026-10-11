---
id: XQL-309-507f995a
title: Data Sources Not parsed or Onboarded Properly
category: investigation
dataset: unknown_unknown_raw
tags:
  - fields
  - unknown_unknown_raw
  - source:dataset
---

# Data Sources Not parsed or Onboarded Properly

**Dataset**: `unknown_unknown_raw`

```sql
dataset = unknown_unknown_raw
| fields _time,_reporting_device_ip, _final_reporting_device_ip ,  _collector_name , _collector_type ,_raw_log ,_broker_device_name , _broker_ip_address , _broker_hostname,*
```

## When to use

Lists the data sources that are not paired with the out-of-the-box content onboarding and parsing

## Variations

_(No variations are documented for this entry.)_
