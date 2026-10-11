---
id: XQL-137-7ec29702
title: Cortex XSIAM JAMF Monitoring - Custom XQL Widget
category: investigation
dataset: jamf_pro_raw
tags:
  - comp
  - sort
  - view
---

# Cortex XSIAM JAMF Monitoring - Custom XQL Widget

**Dataset**: `jamf_pro_raw`

```sql
dataset = jamf_pro_raw
| comp count(device_name) as device_count by device_model
| sort desc device_model
| view graph type = pie xaxis = device_model yaxis = device_count
```

## When to use

Cortex XSIAM JAMF Monitoring - Custom XQL Widget. Queries the `jamf_pro_raw` dataset directly. Uses stages: `comp`, `sort`, `view`.

## Variations

_(No variations are documented for this entry.)_
