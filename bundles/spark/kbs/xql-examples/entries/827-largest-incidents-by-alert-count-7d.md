---
id: XQL-827-05416ba3
title: Largest incidents by alert count (7d)
category: investigation
dataset: incidents
tags:
  - filter
  - fields
  - sort
  - limit
  - incidents
---

# Largest incidents by alert count (7d)

**Dataset**: `incidents`

```sql
config timeframe = 7d
| dataset = incidents
| filter alert_count > 0
| fields _time, incident_id, name, alert_count, critical_severity_alert_count, high_severity_alert_count, severity, status
| sort desc alert_count
| limit 10
```

## When to use

Largest incidents by alert count + breakdown of critical/high. Field is `name` in this tenant (not `incident_name`).

## Variations

_(No variations are documented for this entry.)_
