---
id: XQL-050-e758f3ac
title: Cortex XSIAM Security Incidents - Custom XQL Widget
category: investigation
dataset: panw_ngfw_url_raw
tags:
  - alter
  - comp
  - fields
  - filter
  - limit
  - sort
---

# Cortex XSIAM Security Incidents - Custom XQL Widget

**Dataset**: `panw_ngfw_url_raw`

```sql
dataset = panw_ngfw_url_raw
| filter url_category_list contains "command-and-control" or url_category_list contains "malware" or url_category_list contains "phishing" or url_category_list contains "greyware"
//| filter url_category not in ("catch-all", "computer-and-internet-info")
| alter test = arrayindex(split(url_category_list, ","), 1)
| fields source_ip, from_zone, dest_ip, to_zone, url_*, app, to_zone, test
| comp count(url_domain) as hits, values(app) as application_id, values(arrayindex(split(url_category_list, ","), 1)) as url_categories by url_domain
| sort desc hits
| limit 10
```

## When to use

Cortex XSIAM Security Incidents - Custom XQL Widget. Queries the `panw_ngfw_url_raw` dataset directly, filtered on `url_category_list contains "command-and-control" or url_category_list contains "malware" or url_category_list contains "phishing" or url_cat`. Uses stages: `filter`, `alter`, `fields`, `comp`, `sort`, `limit`.

## Variations

_(No variations are documented for this entry.)_
