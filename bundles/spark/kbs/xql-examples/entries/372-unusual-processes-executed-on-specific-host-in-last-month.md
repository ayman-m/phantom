---
id: XQL-372-6c882c31
title: Unusual Processes Executed on Specific Host in Last Month
category: investigation
dataset: xdr_data
tags:
  - config
  - filter
  - fields
  - comp
  - sort
  - xdr_data
  - source:dataset
---

# Unusual Processes Executed on Specific Host in Last Month

**Dataset**: `xdr_data`

```sql
config timeframe = 30d case_sensitive = false |
dataset = xdr_data |
filter agent_hostname = $host |
fields action_process_image_sha256 as sha256sig, action_process_image_path as path, event_id, agent_hostname as hostname  |
comp count(event_id) as counter by sha256sig, path,hostname |
filter counter < 3 |
sort desc counter
```

## When to use

Lists unusual processes that were executed on a specific host in the last month

## Variations

_(No variations are documented for this entry.)_
