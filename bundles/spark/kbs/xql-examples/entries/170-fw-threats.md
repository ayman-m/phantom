---
id: XQL-170-eab71c72
title: FW Threats
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - fields
  - panw_ngfw_threat_raw
  - source:dataset
---

# FW Threats

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw | fields _collector_type, _device_id  , log_source   , _log_type , severity , app, sub_type , rule_matched , log_type , threat_category , threat_id , threat_name , action , source_port , source_ip , dest_ip , dest_port , app , app_category , url_category , url_category
```

## When to use

FW Threats. Queries the `panw_ngfw_threat_raw` dataset directly. Uses stages: `fields`.

## Variations

_(No variations are documented for this entry.)_
