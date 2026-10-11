---
id: XQL-789-cf378833
title: Long DNS queries — possible tunneling (24h, T1071.004)
category: detection
dataset: xdr_data
tags:
  - filter
  - alter
  - fields
  - sort
  - limit
  - xdr_data
  - network
  - dns
  - T1071.004
---

# Long DNS queries — possible tunneling (24h, T1071.004)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK and action_remote_port = 53
| filter dns_query_name != null
| alter q_len = len(dns_query_name)
| filter q_len > 100
| fields _time, agent_hostname, dns_query_name, q_len
| sort desc q_len
| limit 10
```

## When to use

Long DNS query names (>100 chars) — DNS tunneling indicator (MITRE T1071.004 Application Layer Protocol: DNS). Tunnel encodings produce abnormally long labels.

## Variations

_(No variations are documented for this entry.)_
