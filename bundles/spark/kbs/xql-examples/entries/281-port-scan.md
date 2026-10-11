---
id: XQL-281-f9ee195d
title: Port Scan
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - datamodel
  - filter
  - alter
  - bin
  - comp
  - panw_ngfw_traffic_raw
  - source:datamodel
---

# Port Scan

**Dataset**: `panw_ngfw_traffic_raw`

```sql
datamodel dataset = panw_ngfw_traffic_raw | filter xdm.target.ipv4 = "87.200.238.123" | alter bin_time  = _time | bin bin_time span = 5M | 
comp earliest(_time) as First_eventtime,
       latest(_time) as Latest_eventtime,
    values(xdm.target.port) as Target_Ports,
       count(xdm.target.port) as Count_Target_Ports,
       values(xdm.target.ipv4) as Target_IP,
       values(xdm.event.description) as Event_Details by bin_time,
       xdm.source.ipv4,
       xdm.network.ip_protocol
```

## When to use

Port Scan. XDM-normalized query over `panw_ngfw_traffic_raw`, filtered on `xdm.target.ipv4 = "87.200.238.123"`. Uses stages: `datamodel`, `filter`, `alter`, `bin`, `comp`.

## Variations

_(No variations are documented for this entry.)_
