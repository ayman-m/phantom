---
id: XQL-746-d3613d2f
title: Uppercase agent_hostname normalization (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - alter
  - comp
  - sort
  - limit
  - xdr_data
  - string
---

# Uppercase agent_hostname normalization (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS
| alter host_upper = uppercase(agent_hostname)
| comp count() as cnt by host_upper
| sort desc cnt
| limit 10
```

## When to use

Normalizes hostnames to uppercase for case-insensitive aggregation. Useful when the same host appears with mixed-case names due to legacy logging.

## Variations

_(No variations are documented for this entry.)_
