---
id: XQL-794-03b00866
title: Hosts with >1GB outbound in 1 hour
category: detection
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

# Hosts with >1GB outbound in 1 hour

**Dataset**: `xdr_data`

```sql
config timeframe = 1h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK
| comp sum(action_total_upload) as upload_bytes by agent_hostname
| filter upload_bytes > 1000000000
| sort desc upload_bytes
| limit 10
```

## When to use

Heavy uploaders in a 1-hour window (>1GB). Tight time window catches active exfiltration; threshold filters out cumulative noise.

## Variations

_(No variations are documented for this entry.)_
