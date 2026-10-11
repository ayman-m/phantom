---
id: XQL-841-b1a37669
title: Living-off-the-land binary with network egress (24h)
category: detection
dataset: xdr_data
tags:
  - filter
  - iploc
  - fields
  - sort
  - limit
  - xdr_data
  - network
  - lolbin
  - geo
---

# Living-off-the-land binary with network egress (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK and actor_process_image_name != null
| filter lowercase(actor_process_image_name) in ("certutil.exe", "bitsadmin.exe", "curl.exe", "wget.exe")
| filter action_remote_ip != null and not incidr(action_remote_ip, "10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16")
| iploc action_remote_ip loc_country
| fields _time, agent_hostname, actor_process_image_name, action_remote_ip, loc_country, action_total_upload
| sort desc _time
| limit 10
```

## When to use

LOLBin network egress detection enriched with destination geo. Combines `filter` IN-clause + `incidr` exclusion + `iploc` enrichment — high-fidelity hunting query for exfil-via-LOLBin.

## Variations

_(No variations are documented for this entry.)_
