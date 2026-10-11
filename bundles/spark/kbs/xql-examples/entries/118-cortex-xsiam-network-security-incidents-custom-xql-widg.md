---
id: XQL-118-2b68c48c
title: Cortex XSIAM Network Security Incidents - Custom XQL Widget
category: investigation
dataset: panw_ngfw_
tags:
  - comp
  - fields
  - filter
  - iploc
  - sort
---

# Cortex XSIAM Network Security Incidents - Custom XQL Widget

**Dataset**: `panw_ngfw_`

```sql
dataset = panw_ngfw_*
| fields dest_ip, app_category, threat_*, source_ip, to_zone, from_zone, action
| filter from_zone = "internet"
//| filter threat_category contains "spyware"
| filter action contains "reset"
| iploc  source_ip loc_city, loc_region, loc_country, loc_continent, loc_latlon, loc_timezone
//| comp count(dest_ip) as count_dest by threat_category
| comp count(dest_ip) as hit_count by source_ip
| iploc  source_ip loc_country
| sort desc hit_count
```

## When to use

Cortex XSIAM Network Security Incidents - Custom XQL Widget. Queries the `panw_ngfw_` dataset directly, filtered on `from_zone = "internet"`. Uses stages: `fields`, `filter`, `iploc`, `comp`, `sort`.

## Variations

_(No variations are documented for this entry.)_
