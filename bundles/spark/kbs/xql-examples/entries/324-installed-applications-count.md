---
id: XQL-324-bef46220
title: Installed Applications Count
category: investigation
dataset: host_inventory_applications
tags:
  - preset
  - comp
  - sort
  - host_inventory_applications
  - source:preset
---

# Installed Applications Count

**Dataset**: `host_inventory_applications`

```sql
preset = host_inventory_applications
| comp count() as application_counter by application_name, version
| sort desc application_counter
```

## When to use

Counts all installed applications across the environment to ensure visibility into application deployment and supporting compliance with approved software lists

## Variations

_(No variations are documented for this entry.)_
