---
id: XQL-002-d7ca0a10
title: Arista Cloud Vision Wireless_ Alerts (automatically generated)
category: alert-mapping
dataset: arista_cloud_vision_wireless_blackgeneric_alert_raw
tags:
  - alter
  - filter
---

# Arista Cloud Vision Wireless_ Alerts (automatically generated)

**Dataset**: `arista_cloud_vision_wireless_blackgeneric_alert_raw`

```sql
dataset = arista_cloud_vision_wireless_blackgeneric_alert_raw
| filter _alert_data != null
| alter alert_severity = json_extract_scalar(_alert_data, "$.severity")
| alter alert_category = json_extract_scalar(_alert_data, "$.alert_category")
| alter alert_name = json_extract_scalar(_alert_data, "$.alert_name")
| alter alert_description = json_extract_scalar(_alert_data, "$.alert_description")
```

## When to use

Arista Cloud Vision Wireless_ Alerts (automatically generated). Queries the `arista_cloud_vision_wireless_blackgeneric_alert_raw` dataset directly, filtered on `_alert_data != null`. Uses stages: `filter`, `alter`.

## Variations

_(No variations are documented for this entry.)_
