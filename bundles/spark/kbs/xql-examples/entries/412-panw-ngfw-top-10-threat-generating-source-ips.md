---
id: XQL-412-6041016c
title: PANW NGFW | Top 10 Threat-Generating Source IPs
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - comp
  - sort
  - limit
  - panw_ngfw_threat_raw
  - source:dataset
---

# PANW NGFW | Top 10 Threat-Generating Source IPs

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| comp count() as threat_count by source_ip
| sort desc threat_count
| limit 10
```

## When to use

Reveals the top ten Next-Generation-Firewall (NGFW) source IP addresses that generated the most threat logs, helping to identify malicious or compromised hosts in the network

## Variations

_(No variations are documented for this entry.)_
