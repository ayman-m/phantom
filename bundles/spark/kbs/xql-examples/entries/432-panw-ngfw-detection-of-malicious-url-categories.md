---
id: XQL-432-b3daf6ff
title: PANW NGFW | Detection of Malicious URL Categories
category: investigation
dataset: panw_ngfw_url_raw
tags:
  - filter
  - fields
  - panw_ngfw_url_raw
  - source:dataset
---

# PANW NGFW | Detection of Malicious URL Categories

**Dataset**: `panw_ngfw_url_raw`

```sql
dataset = panw_ngfw_url_raw
|filter url_category ~= ".*malware.*|.*ransomware.*|.*adware.*|.*command-and-control.*|.*hijack.*|spyware|.*virus.*|c2" or url_category_list ~= ".*malware.*|.*ransomware.*|.*adware.*|.*command-and-control.*|.*hijack.*|spyware|.*virus.*"
| fields source_ip , source_port , dest_ip , dest_port , action, app, app_category , from_zone , to_zone, user_agent ,*
```

## When to use

Identifies URL categories related to malicious content, such as malware, ransomware, and spyware in the Next-Generation-Firewall (NGFW) events

## Variations

_(No variations are documented for this entry.)_
