---
id: XQL-741-aba5d4ac
title: Top hosts by event-type breakdown (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - sort
  - limit
  - xdr_data
---

# Top hosts by event-type breakdown (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| comp count() as cnt by agent_hostname, event_type
| sort desc cnt
| limit 10
```

## When to use

Per-host activity volume by event type. Useful baseline — which hosts are most active in process, network, file, etc. Spikes in unusual event types per host warrant follow-up.

## Variations

_(No variations are documented for this entry.)_
