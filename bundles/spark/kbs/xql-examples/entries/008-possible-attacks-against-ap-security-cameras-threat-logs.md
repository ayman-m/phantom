---
id: XQL-008-314e78e1
title: Possible Attacks against AP/Security Cameras (THREAT LOGS)
category: detection
dataset: panw_ngfw_threat_raw
tags:
  - comp
  - fields
  - filter
---

# Possible Attacks against AP/Security Cameras (THREAT LOGS)

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| fields app,from_zone,source_ip,source_port,dest_ip, dest_port, to_zone, action, sub_type, dest_device_host, log_source_name, rule_matched, sub_type, log_type, severity, pcap_id, pcap, threat_name, file_name, url_domain, source_user_info_name, threat_category, sub_type, threat_id
| filter incidr(dest_ip, "10.220.10.0/24, 10.220.11.0/24") = True
| filter (from_zone not in ("security_cameras", "noc_wifi", "switch-ap_mgmt", "TAP-FW-1"))
| filter from_zone != "dns" and to_zone != "dns"
//| comp count(dest_ip) as number_of_attempts by source_ip, dest_ip, dest_port, app, from_zone, to_zone, action, rule_matched, log_type
//| filter  number_of_attempts > 50
```

## When to use

Possible Attacks against AP/Security Cameras (THREAT LOGS). Queries the `panw_ngfw_threat_raw` dataset directly, filtered on `incidr(dest_ip, "10.220.10.0/24, 10.220.11.0/24") = True`. Uses stages: `fields`, `filter`, `comp`.

## Variations

_(No variations are documented for this entry.)_
