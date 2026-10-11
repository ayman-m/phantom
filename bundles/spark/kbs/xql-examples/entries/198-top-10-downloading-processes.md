---
id: XQL-198-4476fd87
title: Top 10 downloading processes
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - comp
  - sort
  - limit
  - xdr_data
  - source:dataset
---

# Top 10 downloading processes

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.NETWORK // Filtering by network activity
 | fields action_download, action_remote_ip as remote_ip, action_external_hostname as remote_hostname, actor_process_image_name as process_name // Selecting the relevant fields
 | comp sum(action_download) as total_download by process_name, remote_ip, remote_hostname // Summing the total download by process + ip + host
 | sort desc total_download // Sorting by total download
 | limit 10 // Limiting the results to only the top 10
```

## When to use

Display the top 10 downloading processes per remote host and IP address

## Variations

_(No variations are documented for this entry.)_
