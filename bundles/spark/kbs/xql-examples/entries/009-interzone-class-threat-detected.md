---
id: XQL-009-ee4b82f0
title: Interzone Class Threat Detected
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - fields
  - filter
---

# Interzone Class Threat Detected

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
    threat_category, sub_type, threat_id
| filter rule_matched not contains "Allow Tap"
| filter to_zone != "internet" and from_zone != "internet"
| filter (rule_matched != """RDNS Outbound DNS""")
| filter from_zone != to_zone
| filter app not contains "dns" and to_zone != "dns"
| filter from_zone not contains "noc_" and to_zone != "reg_web"
| filter rule_matched not contains "nate_joel_laptop_to_reg"
| filter to_zone != "tools_mgmt"
```

## When to use

Interzone Class Threat Detected. Queries the `panw_ngfw_threat_raw` dataset directly, filtered on `rule_matched not contains "Allow Tap"`. Uses stages: `fields`, `filter`.

## Variations

_(No variations are documented for this entry.)_
