---
id: XQL-171-b7ca14ba
title: Network Threats
category: investigation
tags:
  - datamodel
  - fields
  - source:unknown
---

# Network Threats

**Dataset**: `(none)`

```sql
datamodel dataset in (panw_ngfw_threat_raw, snort_labids_raw  ) | fields xdm.alert.category , xdm.alert.description , xdm.alert.name , xdm.alert.subcategory , xdm.alert.severity , xdm.observer.product , xdm.source.ipv4 , xdm.source.port , xdm.target.ipv4 , xdm.target.port , xdm.network.ip_protocol
```

## When to use

Network Threats. XQL pattern. Uses stages: `datamodel`, `fields`.

## Variations

_(No variations are documented for this entry.)_
