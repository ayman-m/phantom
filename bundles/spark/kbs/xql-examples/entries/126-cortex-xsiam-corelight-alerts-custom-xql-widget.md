---
id: XQL-126-dd2191ed
title: Cortex XSIAM Corelight Alerts - Custom XQL Widget
category: general
dataset: corelight_http_raw
tags:
  - alter
  - comp
  - fields
  - filter
  - sort
  - view
---

# Cortex XSIAM Corelight Alerts - Custom XQL Widget

**Dataset**: `corelight_http_raw`

```sql
dataset = corelight_http_raw
|fields _path , _raw_log
|filter _path in("yara_corelight") //"notice", "yara_corelight", "intel*"
|alter match_rule = _raw_log -> match_rule, match_meta = json_extract_scalar_array(_raw_log, "$.match_meta")
|filter match_rule not in("DELIVRTO_SUSP_ZIP_Smuggling_Jun01")
|alter match_desc = arrayindex(arrayfilter(match_meta, "@element" contains "description="),0)
|alter match_desc = arrayindex(split(match_desc,"="), 1)
|comp count() as counter by match_desc
|sort desc counter
| view graph type = column subtype = stacked layout = horizontal xaxis = match_desc yaxis = counter series = match_desc default_limit = `false` legend = `false`
```

## When to use

Cortex XSIAM Corelight Alerts - Custom XQL Widget. Queries the `corelight_http_raw` dataset directly, filtered on `_path in("yara_corelight") //"notice", "yara_corelight", "intel*"`. Uses stages: `fields`, `filter`, `alter`, `comp`, `sort`, `view`.

## Variations

_(No variations are documented for this entry.)_
