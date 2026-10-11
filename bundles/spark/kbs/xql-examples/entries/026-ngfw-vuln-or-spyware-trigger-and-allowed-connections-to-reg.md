---
id: XQL-026-5aa07973
title: NGFW Vuln or Spyware trigger and allowed connections to reg_web
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - alter
  - fields
  - filter
---

# NGFW Vuln or Spyware trigger and allowed connections to reg_web

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
/*
| fields app, from_zone, source_ip, source_port, dest_ip, dest_port, to_zone, action,
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
    threat_category, sub_type, threat_id, _reporting_device_ip, source_device_host, dest_device_host  */
| alter threat = threat_name + " (" + to_string(threat_id) + ")"
| filter app not contains "dns"
| filter lowercase(severity) != "informational" and lowercase(severity) != "low"
| filter
    threat_id != 40073     // PowerDNS Authoritative Server Long qname Denial-of-Service Vulnerability
    and threat_id != 57955 // ZGrab Application Layer Scanner Detection
// | filter incidr(dest_ip, "10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16") = false
| filter to_zone = "reg_web"
//| filter lowercase(rule_matched) != "allow tap"
| filter lowercase(action) != "reset-both" and lowercase(action) != "reset-server" and lowercase(action) != "reset-client"
| filter threat_name != "Inline Cloud Analyzed CMD Injection Traffic Detection" // the TAP was removed so we are excluding the inline C2 since it is allowed in
```

## When to use

NGFW Vuln or Spyware trigger and allowed connections to reg_web. Queries the `panw_ngfw_threat_raw` dataset directly, filtered on `app not contains "dns"`. Uses stages: `fields`, `alter`, `filter`.

## Variations

_(No variations are documented for this entry.)_
