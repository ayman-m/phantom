---
id: XQL-133-4ab26f76
title: Cortex XSIAM NUC Monitoring - Custom XQL Widget
category: investigation
dataset: endpoints
tags:
  - comp
  - filter
  - sort
  - view
---

# Cortex XSIAM NUC Monitoring - Custom XQL Widget

**Dataset**: `endpoints`

```sql
dataset = endpoints
|filter endpoint_name contains "SOC"
| comp count(endpoint_id) as agent_count by agent_version
| sort desc agent_count
| view graph type = pie xaxis = agent_version yaxis = agent_count
```

## When to use

Cortex XSIAM NUC Monitoring - Custom XQL Widget. Queries the `endpoints` dataset directly, filtered on `endpoint_name contains "SOC"`. Uses stages: `filter`, `comp`, `sort`, `view`.

## Variations

_(No variations are documented for this entry.)_
