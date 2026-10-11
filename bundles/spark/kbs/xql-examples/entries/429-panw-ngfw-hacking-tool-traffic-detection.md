---
id: XQL-429-b4e38b67
title: PANW NGFW |  Hacking Tool Traffic Detection
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - filter
  - fields
  - panw_ngfw_threat_raw
  - source:dataset
---

# PANW NGFW |  Hacking Tool Traffic Detection

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
|filter threat_category contains  "hacktool"
| fields source_ip , source_port , dest_ip , dest_port , action, app, app_category , threat_category , threat_name , direction_of_attack , from_zone , to_zone ,*
```

## When to use

Identifies Next-Generation-Firewall (NGFW) traffic associated with hacking tools in the network, helping analysts focus on potentially harmful activities

## Variations

_(No variations are documented for this entry.)_
