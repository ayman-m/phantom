---
id: XQL-384-6ff4be1d
title: Analyze Behavior Associated with Specific IP Address in Last Month (Types of traffic/ Protocols used)
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - config
  - fields
  - filter
  - comp
  - panw_ngfw_traffic_raw
  - source:dataset
---

# Analyze Behavior Associated with Specific IP Address in Last Month (Types of traffic/ Protocols used)

**Dataset**: `panw_ngfw_traffic_raw`

```sql
config timeframe = 30d | dataset = panw_ngfw_traffic_raw
| fields source_ip ,dest_ip , app,app_category , users , source_user , action ,sub_type, protocol  , rule_matched ,to_zone , risk_of_app ,url_category //,session_end_reason
| filter source_ip = $ip or dest_ip = $ip
| filter (risk_of_app not contains "Informational")
| comp values(app) as app,values(app_category) as app_category,values(source_user) as source_user,values(action) as action,values(protocol) as protocol,values(rule_matched) as rule_matched,values(to_zone) as to_zone,values(risk_of_app) as risk_of_app,values(url_category) as url_category,values(sub_type) as sub_type by source_ip
| fields source_ip ,protocol ,app, app_category ,url_category , action, *
| filter source_user != null
```

## When to use

Details the communication with a specific IP address (FW rules, protocols, FW zones, FW actions) in the last month, and includes the applicable data related to the IP address

## Variations

_(No variations are documented for this entry.)_
