---
id: XQL-750-6c82ccc7
title: Network events to specific port across all hosts (1h)
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

# Network events to specific port across all hosts (1h)

**Dataset**: `xdr_data`

```sql
config timeframe = 1h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK and action_remote_port = 443
| comp count() as cnt by agent_hostname
| sort desc cnt
| limit 10
```

## When to use

Per-host HTTPS connection count over the last hour. Short timeframe + simple aggregation — useful as a real-time signal during incident response.

## Variations

_(No variations are documented for this entry.)_
