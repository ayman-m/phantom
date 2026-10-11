---
id: XQL-202-291d331b
title: Process port scan
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - comp
  - sort
  - xdr_data
  - source:dataset
---

# Process port scan

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.NETWORK and action_remote_port < 1024 // Filtering by network data and destination port smaller than 1024
 | fields action_local_ip, action_remote_ip, action_remote_port, actor_process_image_name, actor_process_os_pid // Selecting the relevant fields
 | comp count_distinct(action_remote_port) as Total_Ports by action_local_ip, action_remote_ip, actor_process_image_name, actor_process_os_pid // Counting the amount of distinct ports used by the same process between two hosts
 | filter Total_Ports > 50 // Filtering for cases where more than 50 different ports were used
 | sort desc Total_Ports // Sorting in descending order by number of unique ports
```

## When to use

Search for processes scanning a single remote host for over 50 ports

## Variations

_(No variations are documented for this entry.)_
