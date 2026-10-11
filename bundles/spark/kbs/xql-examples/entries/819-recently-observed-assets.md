---
id: XQL-819-96c8afce
title: Recently-observed assets
category: investigation
dataset: asset_inventory
tags:
  - filter
  - fields
  - sort
  - limit
  - asset_inventory
  - xdm
---

# Recently-observed assets

**Dataset**: `asset_inventory`

```sql
dataset = asset_inventory
| filter xdm.asset.last_observed != null
| fields xdm.asset.name, xdm.asset.type.category, xdm.asset.provider, xdm.asset.last_observed
| sort desc xdm.asset.last_observed
| limit 10
```

## When to use

Most-recently-observed assets. Useful for spotting newly-discovered or recently-active assets.

## Variations

_(No variations are documented for this entry.)_
