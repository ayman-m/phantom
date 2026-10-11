---
id: XQL-743-303894f2
title: Categorize destination IPs as internal / public / multicast (24h)
category: detection
dataset: xdr_data
tags:
  - filter
  - alter
  - comp
  - sort
  - limit
  - xdr_data
  - network
  - incidr
  - conditional
---

# Categorize destination IPs as internal / public / multicast (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK and action_remote_ip != null
| alter ip_class = if(incidr(action_remote_ip, "10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16"), "internal", if(incidr(action_remote_ip, "224.0.0.0/4"), "multicast", if(incidr(action_remote_ip, "127.0.0.0/8"), "loopback", "public")))
| comp count() as cnt, sum(action_total_upload) as upload by ip_class, agent_hostname
| sort desc upload
| limit 10
```

## When to use

IP-class labeling via nested `if` + `incidr`. Aggregates upload bytes per (class, host) so you can see per-host traffic distribution by destination type.

## Variations

_(No variations are documented for this entry.)_
