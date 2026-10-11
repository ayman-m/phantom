---
id: XQL-425-fb428e37
title: PANW NGFW | Top Threats by Spyware Category
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - filter
  - comp
  - sort
  - panw_ngfw_threat_raw
  - source:dataset
---

# PANW NGFW | Top Threats by Spyware Category

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| filter threat_category = "spyware"
| comp count() as spyware_count by threat_id, source_ip, dest_ip
| sort desc spyware_count
```

## When to use

Identifies the most frequently detected Next-Generation-Firewall (NGFW) threats categorized as spyware

## Variations

_(No variations are documented for this entry.)_
