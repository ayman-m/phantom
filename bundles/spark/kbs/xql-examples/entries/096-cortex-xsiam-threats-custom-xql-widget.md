---
id: XQL-096-a291dbc2
title: Cortex XSIAM Threats - Custom XQL Widget
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - comp
  - fields
  - filter
  - limit
  - sort
---

# Cortex XSIAM Threats - Custom XQL Widget

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| filter severity not in ("informational", "low")
| filter from_zone != "TAP"
| comp count(_id) as hits by from_zone, to_zone,threat_name, threat_category,severity
| fields from_zone, to_zone, threat_name, threat_category,severity, hits
| sort desc hits
| limit 50
```

## When to use

Cortex XSIAM Threats - Custom XQL Widget. Queries the `panw_ngfw_threat_raw` dataset directly, filtered on `severity not in ("informational", "low")`. Uses stages: `filter`, `comp`, `fields`, `sort`, `limit`.

## Variations

_(No variations are documented for this entry.)_
