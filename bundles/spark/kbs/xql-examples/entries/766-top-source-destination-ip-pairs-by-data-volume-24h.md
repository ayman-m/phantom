---
id: XQL-766-a9183e8e
title: Top source/destination IP pairs by data volume (24h)
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

# Top source/destination IP pairs by data volume (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK
| comp sum(action_total_upload) as bytes_out, sum(action_total_download) as bytes_in, count() as cnt by action_local_ip, action_remote_ip
| sort desc bytes_out
| limit 10
```

## When to use

Top network conversation pairs by outbound volume. Useful for understanding chatty workloads + identifying potential exfiltration flows.

## Variations

_(No variations are documented for this entry.)_
