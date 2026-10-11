---
id: XQL-069-1800f63a
title: Cortex XSIAM Traffic Overview - Custom XQL Widget
category: investigation
dataset: panw_ngfw
tags:
  - alter
  - bin
  - comp
  - dataset
  - sort
  - view
---

# Cortex XSIAM Traffic Overview - Custom XQL Widget

**Dataset**: `panw_ngfw`

```sql
config timeframe between "4d" and "now"
| dataset = panw_ngfw*
| bin _time span =1h
| sort asc  _time
| comp sum(bytes_sent) as sent, sum(bytes_received ) as received by _time
| alter sent_GB = divide(sent, 1073741824), received_GB = divide(received, 1073741824) // 1073741824 = 1024^3
| view graph type = area subtype = stacked show_percentage = `false` xaxis = _time yaxis = sent_GB,received_GB
```

## When to use

Cortex XSIAM Traffic Overview - Custom XQL Widget. XQL pattern. Uses stages: `dataset`, `bin`, `sort`, `comp`, `alter`, `view`.

## Variations

_(No variations are documented for this entry.)_
