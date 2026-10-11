---
id: XQL-355-c3f6194a
title: Top IPs by RDP Connections in Last Month (Event ID 4624)
category: investigation
dataset: microsoft_windows_raw
tags:
  - config
  - alter
  - filter
  - comp
  - sort
  - limit
  - microsoft_windows_raw
  - source:dataset
---

# Top IPs by RDP Connections in Last Month (Event ID 4624)

**Dataset**: `microsoft_windows_raw`

```sql
config timeframe =30D
| dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter IpAddress = event_data -> IpAddress,logonType = event_data -> LogonType
| filter event_id_num = 4624 and logonType ="10"
| comp count() as rdp_connections by IpAddress
| sort desc rdp_connections
| limit 10
```

## When to use

Lists the top IP addresses involved in Remote Desktop Protocol (RDP) connections over the last month based on event ID 4624, and is filtered by logon type 10, the RDP logon

## Variations

_(No variations are documented for this entry.)_
