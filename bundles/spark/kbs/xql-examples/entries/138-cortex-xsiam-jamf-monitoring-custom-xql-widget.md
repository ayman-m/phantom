---
id: XQL-138-7ec29702
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
| comp count(device_name) as model_count by model_display
| sort desc model_display
| view graph type = pie xaxis = model_display yaxis = model_count
```

## When to use

Cortex XSIAM JAMF Monitoring - Custom XQL Widget. Queries the `jamf_pro_raw` dataset directly. Uses stages: `comp`, `sort`, `view`.

## Variations

_(No variations are documented for this entry.)_
