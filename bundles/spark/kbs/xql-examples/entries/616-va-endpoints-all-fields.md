---
id: XQL-616-387650da
title: VA Endpoints - All Fields
category: investigation
dataset: va_endpoints
tags:
  - fields
  - va_endpoints
  - source:dataset
---

# VA Endpoints - All Fields

**Dataset**: `va_endpoints`

```sql
dataset = va_endpoints | fields endpoint_id , endpoint_name , endpoint_type , os_type , severity , severity_score , cves , last_report_time , last_calculation_time
```

## When to use

VA Endpoints - All Fields. Queries the `va_endpoints` dataset directly. Uses stages: `fields`.

## Variations

_(No variations are documented for this entry.)_
