---
id: XQL-319-d2f378e8
title: Endpoints with Security Updates Installed
category: investigation
dataset: host_inventory_kbs
tags:
  - preset
  - filter
  - fields
  - comp
  - sort
  - host_inventory_kbs
  - source:preset
---

# Endpoints with Security Updates Installed

**Dataset**: `host_inventory_kbs`

```sql
preset = host_inventory_kbs
| filter description = "Security Update"
| fields endpoint_name, endpoint_type, name
| comp count() as kb by name
| sort desc name
```

## When to use

Counts the number of endpoints that have security updates applied and provides the specific updates and the number of endpoints using each to ensure patch management visibility

## Variations

_(No variations are documented for this entry.)_
