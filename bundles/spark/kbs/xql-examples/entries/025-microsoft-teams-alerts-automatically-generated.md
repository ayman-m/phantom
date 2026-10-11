---
id: XQL-025-1ce163b0
title: Microsoft Teams Alerts (automatically generated)
category: alert-mapping
dataset: microsoft_teams_generic_alert_raw
tags:
  - alter
  - filter
---

# Microsoft Teams Alerts (automatically generated)

**Dataset**: `microsoft_teams_generic_alert_raw`

```sql
dataset = microsoft_teams_generic_alert_raw
| filter _alert_data != null
| alter alert_severity = json_extract_scalar(_alert_data, "$.severity")
| alter alert_category = json_extract_scalar(_alert_data, "$.alert_category")
| alter alert_name = json_extract_scalar(_alert_data, "$.alert_name")
| alter alert_description = json_extract_scalar(_alert_data, "$.alert_description")
```

## When to use

Microsoft Teams Alerts (automatically generated). Queries the `microsoft_teams_generic_alert_raw` dataset directly, filtered on `_alert_data != null`. Uses stages: `filter`, `alter`.

## Variations

_(No variations are documented for this entry.)_
