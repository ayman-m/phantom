---
id: XQL-714-c30abbdf
title: DNS query volume per host (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - sort
  - limit
  - xdr_data
  - network
  - dns
---

# DNS query volume per host (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK and action_remote_port = 53
| comp count() as dns_queries by agent_hostname
| sort desc dns_queries
| limit 10
```

## When to use

Hosts with abnormally high DNS query volume can indicate DNS tunneling or malware C2 over DNS. The query filters to port 53 to capture DNS-protocol traffic.

## Variations

_(No variations are documented for this entry.)_
