---
id: XQL-055-e758f3ac
title: Cortex XSIAM Security Incidents - Custom XQL Widget
category: investigation
dataset: alerts
tags:
  - comp
  - fields
  - filter
  - sort
---

# Cortex XSIAM Security Incidents - Custom XQL Widget

**Dataset**: `alerts`

```sql
dataset = alerts
| fields alert_name, app_id, app_subcategory, category, fw_name, source_zone_name, destination_zone_name
//| fields alert_name, source_zone_name
| filter source_zone_name != null and source_zone_name != "internet"
| comp count(alert_name) as alert_count, values(arrayindex(source_zone_name,0)) as room, values(category) as category by alert_name
| sort desc alert_count
```

## When to use

Cortex XSIAM Security Incidents - Custom XQL Widget. Queries the `alerts` dataset directly, filtered on `source_zone_name != null and source_zone_name != "internet"`. Uses stages: `fields`, `filter`, `comp`, `sort`.

## Variations

_(No variations are documented for this entry.)_
