---
id: XQL-286-d2ed2050
title: Webinar - Port Scan Query
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - datamodel
  - filter
  - alter
  - bin
  - comp
  - fields
  - panw_ngfw_traffic_raw
  - source:datamodel
---

# Webinar - Port Scan Query

**Dataset**: `panw_ngfw_traffic_raw`

```sql
datamodel dataset = panw_ngfw_traffic_raw 
| filter incidr( xdm.target.ipv4, "87.200.238.123/26") =true | alter bin_time  = _time | bin bin_time span = 5M 
| comp earliest(_time) as First_eventtime,
       latest(_time) as Latest_eventtime,
    values(xdm.target.port) as Target_Ports,
       count(xdm.target.port) as Count_Target_Ports,
       values(xdm.target.ipv4) as Target_IP,
       values(xdm.event.description) as Event_Details by bin_time,
       xdm.source.ipv4,
       xdm.network.ip_protocol
| filter array_length(Target_Ports ) >= 10
| fields xdm.source.ipv4 , Target_IP , Target_Ports
```

## When to use

Webinar - Port Scan Query. XDM-normalized query over `panw_ngfw_traffic_raw`, filtered on `incidr( xdm.target.ipv4, "87.200.238.123/26") =true`. Uses stages: `datamodel`, `filter`, `alter`, `bin`, `comp`, `fields`.

## Variations

_(No variations are documented for this entry.)_
