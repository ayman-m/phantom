---
id: XQL-205-75e3866e
title: Unique processes running per host
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - dedup
  - xdr_data
  - source:dataset
---

# Unique processes running per host

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START and lowercase(agent_hostname) contains lowercase($Hostname) // Filtering by process start events and using a parameter to allow a user to insert a value before execution
 | fields action_process_image_path, action_process_image_sha256 , agent_hostname // Selecting the relevant fields to show
 | dedup action_process_image_sha256 by asc _time // Reducing the results to show only the first execution per hash
```

## When to use

Display all unique hashes executed on a specific host

## Variations

_(No variations are documented for this entry.)_
