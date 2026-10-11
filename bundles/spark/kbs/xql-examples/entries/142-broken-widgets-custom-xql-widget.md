---
id: XQL-142-d782c07a
title: broken_widgets - Custom XQL Widget
category: investigation
dataset: alerts
tags:
  - alter
  - comp
  - fields
  - filter
  - join
  - limit
  - sort
  - view
---

# broken_widgets - Custom XQL Widget

**Dataset**: `alerts`

```sql
dataset = alerts
| fields alert_name, app_id, app_subcategory, category, fw_name, source_zone_name, destination_zone_name
| alter source_zone_name = arrayindex(source_zone_name, 0), destination_zone_name = arrayindex(destination_zone_name, 0)
| filter source_zone_name != null and source_zone_name != "internet"
| join type = left (
    dataset = subnets_lookup
    |filter Name not in("OpenDNS/Umbrella DNS Virtual Appliances", "Tool Mgmt", "", null)
    |fields Name , Location , FirewallZoneName
) as subnets subnets.FirewallZoneName = source_zone_name or subnets.FirewallZoneName = destination_zone_name
//| alter Name = if(Name in(null,""), "General WiFi", Name)
| comp count(alert_name) as alert_count by Name
| sort desc alert_count
| limit 10
| view graph type = column subtype = grouped layout = horizontal xaxis = Name yaxis = alert_count default_limit = `false`
```

## When to use

broken_widgets - Custom XQL Widget. Queries the `alerts` dataset directly, filtered on `source_zone_name != null and source_zone_name != "internet"`. Uses stages: `fields`, `alter`, `filter`, `join`, `comp`, `sort`.

## Variations

_(No variations are documented for this entry.)_
