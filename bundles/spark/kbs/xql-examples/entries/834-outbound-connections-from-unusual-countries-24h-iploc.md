---
id: XQL-834-de30197e
title: Outbound connections from unusual countries (24h, iploc)
category: detection
dataset: xdr_data
tags:
  - filter
  - iploc
  - comp
  - sort
  - limit
  - xdr_data
  - network
  - geo
---

# Outbound connections from unusual countries (24h, iploc)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK and action_remote_ip != null
| filter not incidr(action_remote_ip, "10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8")
| iploc action_remote_ip loc_country
| comp count() as connections, count_distinct(agent_hostname) as hosts by loc_country
| sort desc connections
| limit 10
```

## When to use

Per-country connection count + unique-host count. Useful for spotting unexpected countries in the traffic mix (could indicate compromised egress, VPN routing changes, or attacker C2 in foreign jurisdictions).

## Variations

_(No variations are documented for this entry.)_
