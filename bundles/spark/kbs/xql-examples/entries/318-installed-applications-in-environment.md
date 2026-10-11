---
id: XQL-318-3dc14b75
title: Installed Applications in Environment
category: investigation
dataset: host_inventory_applications
tags:
  - preset
  - fields
  - host_inventory_applications
  - source:preset
---

# Installed Applications in Environment

**Dataset**: `host_inventory_applications`

```sql
preset = host_inventory_applications
| fields install_date, vendor , application_name, raw_version , platform,*
```

## When to use

Lists all applications currently installed on endpoints to help maintain software inventory, detect unauthorized software, and manage software compliance

## Variations

_(No variations are documented for this entry.)_
