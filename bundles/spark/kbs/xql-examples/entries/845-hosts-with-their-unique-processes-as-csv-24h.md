---
id: XQL-845-4bce7967
title: Hosts with their unique processes as CSV (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - alter
  - fields
  - sort
  - limit
  - xdr_data
  - process
  - arraydistinct
  - arraystring
---

# Hosts with their unique processes as CSV (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| comp values(action_process_image_name) as procs by agent_hostname
| alter unique_procs = arraydistinct(procs)
| alter procs_csv = arraystring(unique_procs, ", ")
| alter proc_count = array_length(unique_procs)
| fields agent_hostname, proc_count, procs_csv
| sort desc proc_count
| limit 10
```

## When to use

Per-host unique-process inventory as a CSV string. Chains values → arraydistinct → arraystring for serialization.

## Variations

_(No variations are documented for this entry.)_
