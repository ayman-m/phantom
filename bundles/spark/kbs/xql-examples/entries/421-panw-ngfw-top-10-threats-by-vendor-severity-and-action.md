---
id: XQL-421-6847f3f0
title: PANW NGFW | Top 10 Threats by Vendor Severity and Action
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - comp
  - sort
  - limit
  - panw_ngfw_threat_raw
  - source:dataset
---

# PANW NGFW | Top 10 Threats by Vendor Severity and Action

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| comp count() as threat_count by vendor_severity, action
| sort desc threat_count
| limit 10
```

## When to use

Categorizes the top Next-Generation-Firewall (NGFW) ten threats based on their severity and the actions taken by the firewall

## Variations

_(No variations are documented for this entry.)_
