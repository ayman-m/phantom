---
id: XQL-038-104b9fad
title: ServiceNow Alerts (automatically generated)
category: alert-mapping
dataset: servicenow_generic_alert_raw
tags:
  - alter
  - filter
---

# ServiceNow Alerts (automatically generated)

**Dataset**: `servicenow_generic_alert_raw`

```sql
dataset = servicenow_generic_alert_raw
| filter _alert_data != null
| alter alert_severity = json_extract_scalar(_alert_data, "$.severity")
| alter alert_category = json_extract_scalar(_alert_data, "$.alert_category")
| alter alert_name = json_extract_scalar(_alert_data, "$.alert_name")
| alter alert_description = json_extract_scalar(_alert_data, "$.alert_description")
```

## When to use

ServiceNow Alerts (automatically generated). Queries the `servicenow_generic_alert_raw` dataset directly, filtered on `_alert_data != null`. Uses stages: `filter`, `alter`.

## Variations

_(No variations are documented for this entry.)_
