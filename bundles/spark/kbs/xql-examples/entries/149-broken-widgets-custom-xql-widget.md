---
id: XQL-149-d782c07a
title: broken_widgets - Custom XQL Widget
category: investigation
dataset: corelight_zeek_raw
tags:
  - comp
  - dataset
  - fields
  - filter
  - join
  - view
---

# broken_widgets - Custom XQL Widget

**Dataset**: `corelight_zeek_raw`

```sql
config case_sensitive = false
| dataset = corelight_zeek_raw
| filter (`_path` = """conn""")
| fields uid  , id_orig_p , id_orig_chaddr , id_resp_l2_addr , id_orig_l2_addr , id, id_orig_h , id_resp_h , enrichment_orig_network_name, enrichment_orig_network_ssid, enrichment_orig_room_name, enrichment_resp_network_name, enrichment_resp_network_ssid, enrichment_resp_room_name, conn_state, spcap_url, id_orig_chaddr
| join type = right (dataset = corelight_zeek_raw
| filter (`_path` = """yara_corelight""") | fields match_meta,match_rule,md5,mime_type,sha1,sha256,uid) as a a.uid=uid
| join type = right (dataset = corelight_zeek_raw
| fields _path, uid, id_orig_h as source_ip, id_resp_h as dest_ip, id_orig_p as source_port, id_resp_p as dest_port, id_resp_l2_addr as dest_mac, id_orig_l2_addr as source_mac, payload, payload_printable, alert_signature, alert_signature_id, alert_action, alert_category, alert_action, alert_metadata, alert_severity, alert_rule, service
| filter _path = "suricata_corelight") as t t.uid = uid
| filter (`conn_state` not in (null, """"""))
| comp count() by match_rule
| view graph type = column subtype = grouped layout = horizontal header = "Match Rule" xaxis = match_rule yaxis = count_1 seriescolor("count_1","#e9ec7c") seriestitle("count_1","Total")
```

## When to use

broken_widgets - Custom XQL Widget. XQL pattern, filtered on `(`_path` = """conn""")`. Uses stages: `dataset`, `filter`, `fields`, `join`, `comp`, `view`.

## Variations

_(No variations are documented for this entry.)_
