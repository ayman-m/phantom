---
id: XQL-027-32c03b11
title: Corelight Suricata Alert
category: investigation
dataset: corelight_zeek_raw
tags:
  - fields
  - filter
---

# Corelight Suricata Alert

**Dataset**: `corelight_zeek_raw`

```sql
dataset = corelight_zeek_raw
| fields _path, uid, id_orig_h as source_ip, id_resp_h as dest_ip, id_orig_p as source_port, id_resp_p as dest_port, id_resp_l2_addr as dest_mac, id_orig_l2_addr as source_mac, payload, payload_printable, alert_signature, alert_signature_id, alert_action, alert_category, alert_action, alert_metadata, alert_severity, alert_rule, service, enrichment_orig_network_name, enrichment_orig_network_ssid, enrichment_orig_room_name, enrichment_resp_network_name, enrichment_resp_network_ssid, enrichment_resp_room_name, conn_state, spcap_url, id_orig_chaddr
| filter _path = "suricata_corelight" and ((payload != null and payload != "") or (payload_printable != null and payload_printable != "")) and (alert_metadata contains "signature_severity:medium" or alert_metadata contains "signature_severity:high" or alert_metadata contains "signature_severity:critical")
```

## When to use

Corelight Suricata Alert. Queries the `corelight_zeek_raw` dataset directly, filtered on `_path = "suricata_corelight" and ((payload != null and payload != "") or (payload_printable != null and payload_printable != "")) and (alert`. Uses stages: `fields`, `filter`.

## Variations

_(No variations are documented for this entry.)_
