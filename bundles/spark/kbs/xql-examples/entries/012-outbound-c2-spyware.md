---
id: XQL-012-3da413cb
title: Outbound C2 Spyware
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - alter
  - fields
  - filter
---

# Outbound C2 Spyware

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| fields app,from_zone,source_ip,source_port,dest_ip, dest_port, to_zone, action,
    file_sha_256, sub_type,
    dest_device_host,
    cloud_hostname, log_source_name,
    rule_matched,
    severity,
    pcap_id,
    pcap,
    session_id,
    threat_name,
    file_name, url_domain,
    source_user_info_name,
    threat_category, sub_type, threat_id, users
| alter threat = threat_name + " (" + to_string(threat_id) + ")"
//| filter threat_id != 14978 and threat_id != 14984
//| filter severity != "Informational" and severity != "Low" and severity != "Medium" and severity != null
| filter app not contains "dns"
| filter sub_type = "spyware"
| filter incidr(dest_ip, "10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16") = false and from_zone not in("internet")
| filter rule_matched != "Allow TAP"
| filter file_name contains ".oast."
//| filter to_zone = "internet" and from_zone != "internet"
```

## When to use

Outbound C2 Spyware. Queries the `panw_ngfw_threat_raw` dataset directly, filtered on `threat_id != 14978 and threat_id != 14984`. Uses stages: `fields`, `alter`, `filter`.

## Variations

_(No variations are documented for this entry.)_
