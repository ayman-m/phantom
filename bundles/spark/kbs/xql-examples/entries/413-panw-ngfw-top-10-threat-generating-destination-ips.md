---
id: XQL-413-76bb6b6d
title: PANW NGFW | Top 10 Threat-Generating Destination IPs
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - comp
  - sort
  - limit
  - panw_ngfw_threat_raw
  - source:dataset
---

# PANW NGFW | Top 10 Threat-Generating Destination IPs

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| comp count() as threat_count by dest_ip
| sort desc threat_count
| limit 10
```

## When to use

Identifies the top ten Next-Generation-Firewall (NGFW) destination IP addresses that have received the most traffic associated with threats to identify potential target systems

## Variations

_(No variations are documented for this entry.)_
