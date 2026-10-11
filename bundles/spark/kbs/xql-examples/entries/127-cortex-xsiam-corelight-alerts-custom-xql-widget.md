---
id: XQL-127-dd2191ed
title: Cortex XSIAM Corelight Alerts - Custom XQL Widget
category: general
dataset: corelight_http_raw
tags:
  - alter
  - comp
  - fields
  - filter
  - sort
  - view
---

# Cortex XSIAM Corelight Alerts - Custom XQL Widget

**Dataset**: `corelight_http_raw`

```sql
dataset = corelight_http_raw
|fields _path, alert_signature
|filter _path in("suricata_corelight", "notice", "yara_corelight", "intel*") and alert_signature not in("INFO*","POLICY*","DNS*","ICMP*")
|alter topic = arrayindex(regextract(alert_signature, "^\w+\s([A-Z0-9_]*)"),0), sig_name = arrayindex(regextract(alert_signature, "^[A-Z]{2,5}\s.+?\s(.+)$") , 0)
|alter sig_name = replex(sig_name, "\sgroup\s\d+$","")
|filter topic not in("SNMP","ICMP","USER_AGENTS","DROP","HUNTING","SCAN","ADWARE_PUP","FILE_SHARING") and sig_name not in("syncthing*")
//|view column order = populated
|comp count() as counter by sig_name
|sort desc counter
| view graph type = pie xaxis = sig_name yaxis = counter
```

## When to use

Cortex XSIAM Corelight Alerts - Custom XQL Widget. Queries the `corelight_http_raw` dataset directly, filtered on `_path in("suricata_corelight", "notice", "yara_corelight", "intel*") and alert_signature not in("INFO*","POLICY*","DNS*","ICMP*")`. Uses stages: `fields`, `filter`, `alter`, `view`, `comp`, `sort`.

## Variations

_(No variations are documented for this entry.)_
