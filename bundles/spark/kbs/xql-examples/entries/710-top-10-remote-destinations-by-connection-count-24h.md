---
id: XQL-710-362892cb
title: Top 10 remote destinations by connection count (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - sort
  - limit
  - xdr_data
  - network
---

# Top 10 remote destinations by connection count (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK
| filter action_remote_ip != null
| comp count() as connections by action_remote_ip, action_remote_port
| sort desc connections
| limit 10
```

## When to use

Aggregates outbound + inbound connections by remote IP+port pair. Useful for surfacing top external services + spotting C2-like patterns (high connection count to a single unknown IP).

## Variations

_(No variations are documented for this entry.)_
