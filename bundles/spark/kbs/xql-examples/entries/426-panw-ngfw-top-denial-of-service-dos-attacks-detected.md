---
id: XQL-426-7d57f2f0
title: PANW NGFW | Top Denial of Service (DoS) Attacks Detected
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - filter
  - comp
  - sort
  - panw_ngfw_threat_raw
  - source:dataset
---

# PANW NGFW | Top Denial of Service (DoS) Attacks Detected

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| filter threat_category = "dos"
| comp count() as dos_attack_count by threat_id, source_ip, dest_ip
| sort desc dos_attack_count
```

## When to use

Identifies the most common Denial of Service (DoS) attacks detected by the Next-Generation-Firewall (NGFW)

## Variations

_(No variations are documented for this entry.)_
