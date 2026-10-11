---
id: XQL-357-c65dbf12
title: Top IPs by Kerberos Authentication Failures (Event ID 4771)
category: investigation
dataset: microsoft_windows_raw
tags:
  - alter
  - filter
  - comp
  - sort
  - limit
  - microsoft_windows_raw
  - source:dataset
---

# Top IPs by Kerberos Authentication Failures (Event ID 4771)

**Dataset**: `microsoft_windows_raw`

```sql
dataset = microsoft_windows_raw
| alter event_id_num = to_integer(event_id)
| alter IpAddress = event_data -> IpAddress,
        failure_reason = arrayindex(regextract(message, "Failure Code:\s*(.+?)\s+"), 0)
| filter event_id_num = 4771
| comp count() as auth_failures by IpAddress
| sort desc auth_failures
| limit 10
```

## When to use

Lists the IP addresses with the most Kerberos authentication failures based on event ID 4771, and includes the failure reason and IP address details

## Variations

_(No variations are documented for this entry.)_
