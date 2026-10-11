---
id: XQL-833-3a926546
title: Top remote IPs enriched with geolocation (24h, iploc)
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - sort
  - iploc
  - fields
  - limit
  - xdr_data
  - network
  - geo
---

# Top remote IPs enriched with geolocation (24h, iploc)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK and action_remote_ip != null
| filter not incidr(action_remote_ip, "10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16")
| comp count() as connections, sum(action_total_upload) as upload by action_remote_ip
| sort desc connections
| iploc action_remote_ip loc_country, loc_city, loc_region
| fields action_remote_ip, loc_country, loc_city, loc_region, connections, upload
| limit 10
```

## When to use

External destinations enriched with country/city/region via the `iploc` stage. The geolocation columns (loc_country, loc_city, loc_region, loc_latlon, loc_timezone) are auto-added by iploc — no setup needed. Useful for surfacing unexpected geographies in outbound traffic.

## Variations

_(No variations are documented for this entry.)_
