---
id: XQL-157-e9fc23f7
title: Cortex XSIAM Cisco Umbrella DNS - Custom XQL Widget
category: investigation
dataset: cisco_umbrella_raw
tags:
  - comp
  - filter
  - limit
  - sort
  - view
---

# Cortex XSIAM Cisco Umbrella DNS - Custom XQL Widget

**Dataset**: `cisco_umbrella_raw`

```sql
dataset = cisco_umbrella_raw
|filter action contains "blocked"
| comp count(catagories) as counter by catagories
|sort desc counter
|limit 5
| view graph type = pie xaxis = catagories yaxis = counter seriestitle("counter","Blocked DNS")
```

## When to use

Cortex XSIAM Cisco Umbrella DNS - Custom XQL Widget. Queries the `cisco_umbrella_raw` dataset directly, filtered on `action contains "blocked"`. Uses stages: `filter`, `comp`, `sort`, `limit`, `view`.

## Variations

_(No variations are documented for this entry.)_
