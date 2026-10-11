---
id: XQL-813-eb86396b
title: Host inventory by OS type
category: investigation
dataset: host_inventory
tags:
  - filter
  - comp
  - sort
  - limit
  - host_inventory
---

# Host inventory by OS type

**Dataset**: `host_inventory`

```sql
dataset = host_inventory
| filter os_type != null
| comp count() as cnt by os_type
| sort desc cnt
| limit 10
```

## When to use

Discovered host distribution by OS type. Field is `os_type` (not `operating_system_family`).

## Variations

_(No variations are documented for this entry.)_
