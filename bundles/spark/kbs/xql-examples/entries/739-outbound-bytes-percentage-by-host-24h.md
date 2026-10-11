---
id: XQL-739-b747c169
title: Outbound bytes percentage by host (24h)
category: detection
dataset: xdr_data
tags:
  - filter
  - comp
  - alter
  - sort
  - limit
  - xdr_data
  - network
  - exfil
  - math
---

# Outbound bytes percentage by host (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK
| comp sum(action_total_upload) as upload, sum(action_total_download) as download by agent_hostname
| alter total_bytes = add(upload, download)
| filter total_bytes > 0
| alter upload_pct = multiply(divide(upload, total_bytes), 100)
| sort desc upload_pct
| limit 10
```

## When to use

Computes upload/download ratio per host using XQL math functions (add, divide, multiply). High upload_pct = exfiltration signal — host sending much more than receiving.

## Variations

_(No variations are documented for this entry.)_
