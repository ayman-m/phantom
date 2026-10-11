---
id: XQL-711-8e67530f
title: Top hosts by outbound upload bytes (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - sort
  - limit
  - xdr_data
  - network
  - exfil
---

# Top hosts by outbound upload bytes (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK
| comp sum(action_total_upload) as total_upload by agent_hostname
| sort desc total_upload
| limit 10
```

## When to use

Aggregate upload bytes per host to identify data-exfiltration candidates. Hosts with anomalously high upload totals + minimal legitimate egress reason are worth investigating.

## Variations

_(No variations are documented for this entry.)_
