---
id: XQL-431-8bc4997a
title: PANW NGFW | Cryptocurrency Mining Traffic Detection
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - filter
  - fields
  - panw_ngfw_traffic_raw
  - source:dataset
---

# PANW NGFW | Cryptocurrency Mining Traffic Detection

**Dataset**: `panw_ngfw_traffic_raw`

```sql
dataset = panw_ngfw_traffic_raw
|filter app in ("bitcoin", "coinhave", "coinblind", "coinimp", "coinnebula", "crypto-loot", "deepminer", "jsecoin", "litecoin", "mineralt", "webmine", "cryptonoter", "coinhive")
| fields app, to_zone, dest_device_host ,dest_ip, dest_port, log_source_name, action, rule_matched, session_id, from_zone, source_ip, source_port, source_user_info_name, *
```

## When to use

Detects Next-Generation-Firewall (NGFW) traffic associated with cryptocurrency mining applications, such as bitcoin and other miners

## Variations

_(No variations are documented for this entry.)_
