---
id: XQL-792-ac13f3c1
title: Unique remote IPs per host (24h)
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

# Unique remote IPs per host (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK and action_remote_ip != null
| comp count_distinct(action_remote_ip) as unique_destinations by agent_hostname
| sort desc unique_destinations
| limit 10
```

## When to use

Per-host unique-destination count. Hosts with abnormally high destination counts could be scanners (legitimate or otherwise) or compromised hosts spraying connections.

## Variations

_(No variations are documented for this entry.)_
