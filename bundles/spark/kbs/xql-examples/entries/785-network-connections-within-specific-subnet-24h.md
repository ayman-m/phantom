---
id: XQL-785-a68e1225
title: Network connections within specific subnet (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - sort
  - limit
  - xdr_data
  - network
  - incidr
---

# Network connections within specific subnet (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK and action_remote_ip != null
| filter incidr(action_remote_ip, "10.0.0.0/8")
| comp count() as cnt by action_remote_ip
| sort desc cnt
| limit 10
```

## When to use

Connections targeting the 10/8 RFC1918 range. Useful for understanding internal-network communication patterns.

## Variations

_(No variations are documented for this entry.)_
