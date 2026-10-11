---
id: XQL-325-579bafa4
title: Ingested Data Sources in XSIAM
category: general
dataset: metrics_view
tags:
  - preset
  - filter
  - alter
  - fields
  - dedup
  - sort
  - metrics_view
  - source:preset
---

# Ingested Data Sources in XSIAM

**Dataset**: `metrics_view`

```sql
preset = metrics_view
| filter _vendor contains "*"
| alter ven_product = concat(_vendor, " (", _product , ") ")
| fields ven_product
| dedup ven_product
| sort asc ven_product
```

## When to use

Lists the data sources currently being ingested into XSIAM and provides the vendor and product details to help users confirm active ingestion streams

## Variations

_(No variations are documented for this entry.)_
