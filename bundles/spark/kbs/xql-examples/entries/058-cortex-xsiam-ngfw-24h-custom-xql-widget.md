---
id: XQL-058-423f4558
title: Cortex XSIAM NGFW 24h - Custom XQL Widget
category: investigation
dataset: incidents
tags:
  - comp
  - filter
  - view
---

# Cortex XSIAM NGFW 24h - Custom XQL Widget

**Dataset**: `incidents`

```sql
dataset = incidents
| filter status = ENUM.RESOLVED_AUTO_RESOLVE and alert_sources = "FW"
| comp count(status)
| view graph type = single subtype = standard header = "Auto Closed 24h" yaxis = count_1 headcolor = "#08ff4b" headerfontsize = 60
```

## When to use

Cortex XSIAM NGFW 24h - Custom XQL Widget. Queries the `incidents` dataset directly, filtered on `status = ENUM.RESOLVED_AUTO_RESOLVE and alert_sources = "FW"`. Uses stages: `filter`, `comp`, `view`.

## Variations

_(No variations are documented for this entry.)_
