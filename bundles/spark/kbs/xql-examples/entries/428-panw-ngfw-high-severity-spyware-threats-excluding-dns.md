---
id: XQL-428-7f2a1608
title: PANW NGFW | High-Severity Spyware Threats Excluding DNS
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - filter
  - fields
  - panw_ngfw_threat_raw
  - source:dataset
---

# PANW NGFW | High-Severity Spyware Threats Excluding DNS

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
|filter severity != "Informational" and severity != "Low" and severity != "Medium" and severity != null
|filter app not contains "dns"
|filter sub_type = "spyware"
| fields source_ip , source_port , dest_ip , dest_port , action, app, app_category , threat_category , threat_name , direction_of_attack , from_zone , to_zone ,*
```

## When to use

Lists high-severity spyware threats detected in the network and filters out DNS-related traffic

## Variations

_(No variations are documented for this entry.)_
