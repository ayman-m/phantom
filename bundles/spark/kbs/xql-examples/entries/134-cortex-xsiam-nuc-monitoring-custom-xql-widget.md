---
id: XQL-134-4ab26f76
title: Cortex XSIAM NUC Monitoring - Custom XQL Widget
category: investigation
dataset: endpoints
tags:
  - comp
  - filter
  - view
---

# Cortex XSIAM NUC Monitoring - Custom XQL Widget

**Dataset**: `endpoints`

```sql
dataset = endpoints
|filter endpoint_name contains "SOC"
| filter endpoint_status in (CONNECTED, CONNECTION_LOST)
| comp count(endpoint_id) as total by endpoint_status
| view graph type = pie xaxis = endpoint_status yaxis = total
```

## When to use

Cortex XSIAM NUC Monitoring - Custom XQL Widget. Queries the `endpoints` dataset directly, filtered on `endpoint_name contains "SOC"`. Uses stages: `filter`, `comp`, `view`.

## Variations

_(No variations are documented for this entry.)_
