---
id: XQL-818-2475e5c9
title: Assets by class within category (XDM)
category: investigation
dataset: asset_inventory
tags:
  - filter
  - comp
  - sort
  - limit
  - asset_inventory
  - xdm
---

# Assets by class within category (XDM)

**Dataset**: `asset_inventory`

```sql
dataset = asset_inventory
| filter xdm.asset.type.class != null
| comp count() as cnt by xdm.asset.type.category, xdm.asset.type.class
| sort desc cnt
| limit 10
```

## When to use

Hierarchical asset breakdown: category → class. XDM normalizes these as a 2-level taxonomy.

## Variations

_(No variations are documented for this entry.)_
