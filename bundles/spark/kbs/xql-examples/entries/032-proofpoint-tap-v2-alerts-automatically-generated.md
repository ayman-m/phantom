---
id: XQL-032-83d9e0d1
title: Proofpoint TAP v2 Alerts (automatically generated)
category: alert-mapping
dataset: proofpoint_tap_v2_generic_alert_raw
tags:
  - alter
  - filter
---

# Proofpoint TAP v2 Alerts (automatically generated)

**Dataset**: `proofpoint_tap_v2_generic_alert_raw`

```sql
dataset = proofpoint_tap_v2_generic_alert_raw
| filter _alert_data != null
| alter alert_severity = json_extract_scalar(_alert_data, "$.severity")
| alter alert_category = json_extract_scalar(_alert_data, "$.alert_category")
| alter alert_name = json_extract_scalar(_alert_data, "$.alert_name")
| alter alert_description = json_extract_scalar(_alert_data, "$.alert_description")
```

## When to use

Proofpoint TAP v2 Alerts (automatically generated). Queries the `proofpoint_tap_v2_generic_alert_raw` dataset directly, filtered on `_alert_data != null`. Uses stages: `filter`, `alter`.

## Variations

_(No variations are documented for this entry.)_
