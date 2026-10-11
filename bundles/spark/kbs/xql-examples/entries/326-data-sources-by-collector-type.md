---
id: XQL-326-10ed9036
title: Data Sources by Collector Type
category: investigation
dataset: metrics_view
tags:
  - preset
  - filter
  - alter
  - dedup
  - fields
  - metrics_view
  - source:preset
---

# Data Sources by Collector Type

**Dataset**: `metrics_view`

```sql
preset = metrics_view
| filter _collector_type in ($collector_type)
| alter ven_product = concat(_vendor, " (", _product , ") ")
| dedup ven_product
| fields _collector_type, ven_product
```

## When to use

Lists the data sources ingested using a specified collector type to provide details on vendors and products associated with each collector type

## Variations

_(No variations are documented for this entry.)_
