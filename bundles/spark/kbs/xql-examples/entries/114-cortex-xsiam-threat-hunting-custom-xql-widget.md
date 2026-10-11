---
id: XQL-114-b77155f8
title: Cortex XSIAM Threat Hunting - Custom XQL Widget
category: investigation
dataset: corelight_zeek_raw
tags:
  - comp
  - fields
  - filter
  - view
---

# Cortex XSIAM Threat Hunting - Custom XQL Widget

**Dataset**: `corelight_zeek_raw`

```sql
dataset = corelight_zeek_raw
| fields _path, uid, id_orig_h as source_ip, id_resp_h as dest_ip, id_orig_p as source_port, id_resp_p as dest_port, id_resp_l2_addr as dest_mac, id_orig_l2_addr as source_mac, payload, payload_printable, alert_signature, alert_signature_id, alert_action, alert_category, alert_action, alert_metadata, alert_severity, alert_rule, service
| filter _path = "suricata_corelight"
| comp count () by alert_category
| view graph type = pie header = "Suricata Alert Category" xaxis = alert_category yaxis = count_1 seriestitle("count_1","Total")
```

## When to use

Cortex XSIAM Threat Hunting - Custom XQL Widget. Queries the `corelight_zeek_raw` dataset directly, filtered on `_path = "suricata_corelight"`. Uses stages: `fields`, `filter`, `comp`, `view`.

## Variations

_(No variations are documented for this entry.)_
