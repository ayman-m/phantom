---
id: XQL-836-15499912
title: Network destinations sortable by IP-integer order (24h, ip_to_int)
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - alter
  - sort
  - limit
  - xdr_data
  - network
  - ip_to_int
---

# Network destinations sortable by IP-integer order (24h, ip_to_int)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK and action_remote_ip != null
| filter not incidr(action_remote_ip, "10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16")
| comp count() as connections by action_remote_ip
| alter ip_int = ip_to_int(action_remote_ip)
| sort asc ip_int
| limit 10
```

## When to use

External IPs sorted in numerical (IP-integer) order. `ip_to_int(ipv4)` converts to a 32-bit integer for proper sorting. Useful for range-based analysis + identifying nearby IPs in the same subnet.

## Variations

_(No variations are documented for this entry.)_
