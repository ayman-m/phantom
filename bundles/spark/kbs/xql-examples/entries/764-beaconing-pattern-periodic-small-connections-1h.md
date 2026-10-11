---
id: XQL-764-f3391d29
title: Beaconing pattern — periodic small connections (1h)
category: detection
dataset: xdr_data
tags:
  - filter
  - comp
  - sort
  - limit
  - xdr_data
  - network
  - beacon
  - c2
---

# Beaconing pattern — periodic small connections (1h)

**Dataset**: `xdr_data`

```sql
config timeframe = 1h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK and action_remote_ip != null
| comp count() as connections, sum(action_total_upload) as upload, sum(action_total_download) as download by agent_hostname, action_remote_ip
| filter connections >= 30 and upload < 100000
| sort desc connections
| limit 10
```

## When to use

Likely beaconing — many small connections to a single remote IP. Threshold: 30+ connections + <100KB total upload in 1 hour. C2 callbacks typically match this signature.

## Variations

_(No variations are documented for this entry.)_
