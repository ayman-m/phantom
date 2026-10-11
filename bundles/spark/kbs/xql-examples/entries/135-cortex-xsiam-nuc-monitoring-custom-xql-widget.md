---
id: XQL-135-4ab26f76
title: Cortex XSIAM NUC Monitoring - Custom XQL Widget
category: investigation
dataset: alerts
tags:
  - comp
  - filter
  - limit
  - sort
---

# Cortex XSIAM NUC Monitoring - Custom XQL Widget

**Dataset**: `alerts`

```sql
dataset = alerts
| filter host_name contains "SOC"
| comp count(alert_id) as alert_count by host_name
| sort desc alert_count
| limit 20
```

## When to use

Cortex XSIAM NUC Monitoring - Custom XQL Widget. Queries the `alerts` dataset directly, filtered on `host_name contains "SOC"`. Uses stages: `filter`, `comp`, `sort`, `limit`.

## Variations

_(No variations are documented for this entry.)_
