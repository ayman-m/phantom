---
id: XQL-028-311f222f
title: NGFW Inline/ATP Alerts on TAP
category: general
dataset: panw_ngfw_threat_raw
tags:
  - alter
  - fields
  - filter
---

# NGFW Inline/ATP Alerts on TAP

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw |
fields app, from_zone, source_ip, source_port, dest_ip, dest_port, to_zone, action,
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
| alter threat = threat_name + " (" + to_string(threat_id) + ")"
// | filter incidr(dest_ip, "10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16") = false
// | filter to_zone = "reg_web"                    // Irrelevant on TAP as the to_zone is TAP-FW-1
| filter lowercase(rule_matched) = "allow tap"     // Inline C2 / ATP alerts are only enabled on TAP NGFWs
| filter lowercase(threat_name) contains "inline"  // Inline C2
// | filter lowercase(action) != "reset-both" and lowercase(action) != "reset-server" and lowercase(action) != "reset-client"
```

## When to use

NGFW Inline/ATP Alerts on TAP. Queries the `panw_ngfw_threat_raw` dataset directly, filtered on `incidr(dest_ip, "10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16") = false`. Uses stages: `fields`, `alter`, `filter`.

## Variations

_(No variations are documented for this entry.)_
