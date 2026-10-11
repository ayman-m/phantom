---
id: XQL-169-ca0c6883
title: Snort XDM
category: investigation
dataset: snort_ids_raw
tags:
  - datamodel
  - fields
  - snort_ids_raw
  - source:datamodel
---

# Snort XDM

**Dataset**: `snort_ids_raw`

```sql
datamodel dataset = snort_ids_raw | fields xdm.source.ipv4, xdm.target.ipv4, xdm.target.port, xdm.source.port, xdm.source.host.mac_addresses, xdm.target.host.mac_addresses, xdm.observer.action, xdm.event.description ,
xdm.source.sent_packets,
xdm.event.type,
xdm.source.host.hostname,
xdm.alert.name,
xdm.target.module.directory,
xdm.source.application.name,
xdm.target.application.name,
xdm.alert.severity,
xdm.network.ip_protocol
```

## When to use

Snort XDM. XDM-normalized query over `snort_ids_raw`. Uses stages: `datamodel`, `fields`.

## Variations

_(No variations are documented for this entry.)_
