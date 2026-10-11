---
id: XQL-148-d782c07a
title: broken_widgets - Custom XQL Widget
category: investigation
dataset: corelight_zeek_raw
tags:
  - comp
  - fields
  - filter
  - view
---

# broken_widgets - Custom XQL Widget

**Dataset**: `corelight_zeek_raw`

```sql
dataset = corelight_zeek_raw
| fields _path, uid, id_orig_h as source_ip, id_resp_h as dest_ip, id_orig_p as source_port, id_resp_p as dest_port, id_resp_l2_addr as dest_mac, id_orig_l2_addr as source_mac, payload, payload_printable, alert_signature, alert_signature_id, alert_action, alert_category, alert_action, alert_metadata, alert_severity, alert_rule, service
| filter _path = "suricata_corelight" and alert_signature contains "ETPRO HUNTING"
| comp count () by alert_signature
| view graph type = pie xaxis = alert_signature yaxis = count_1 seriestitle("count_1","Total")
```

## When to use

broken_widgets - Custom XQL Widget. Queries the `corelight_zeek_raw` dataset directly, filtered on `_path = "suricata_corelight" and alert_signature contains "ETPRO HUNTING"`. Uses stages: `fields`, `filter`, `comp`, `view`.

## Variations

_(No variations are documented for this entry.)_
