---
id: XQL-816-9e8afba0
title: Assets by category (XDM)
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

# Assets by category (XDM)

**Dataset**: `asset_inventory`

```sql
dataset = asset_inventory
| filter xdm.asset.type.category != null
| comp count() as cnt by xdm.asset.type.category
| sort desc cnt
| limit 10
```

## When to use

Asset distribution by category. asset_inventory uses XDM schema — category is `xdm.asset.type.category`.

## Variations

_(No variations are documented for this entry.)_
