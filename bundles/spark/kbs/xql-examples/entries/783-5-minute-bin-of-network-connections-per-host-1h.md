---
id: XQL-783-3d147b2f
title: 5-minute bin of network connections per host (1h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - bin
  - comp
  - sort
  - limit
  - xdr_data
  - network
---

# 5-minute bin of network connections per host (1h)

**Dataset**: `xdr_data`

```sql
config timeframe = 1h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK
| bin _time span = 5m
| comp count() as connections by _time, agent_hostname
| sort desc _time, connections
| limit 10
```

## When to use

Fine-grained (5min) network connection rate per host. Useful for tight burst-detection windows during incident response.

## Variations

_(No variations are documented for this entry.)_
