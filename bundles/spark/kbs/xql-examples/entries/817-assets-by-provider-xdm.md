---
id: XQL-817-cbf0d922
title: Assets by provider (XDM)
category: investigation
dataset: asset_inventory
tags:
  - filter
  - comp
  - sort
  - limit
  - asset_inventory
  - xdm
  - cloud
---

# Assets by provider (XDM)

**Dataset**: `asset_inventory`

```sql
dataset = asset_inventory
| filter xdm.asset.provider != null
| comp count() as cnt by xdm.asset.provider, xdm.asset.realm
| sort desc cnt
| limit 10
```

## When to use

Asset count by cloud provider + realm via the XDM schema. Reveals multi-cloud distribution.

## Variations

_(No variations are documented for this entry.)_
