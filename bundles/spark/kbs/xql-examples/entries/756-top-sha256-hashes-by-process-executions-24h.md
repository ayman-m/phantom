---
id: XQL-756-edca7344
title: Top SHA256 hashes by process executions (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - sort
  - limit
  - xdr_data
  - process
  - hash
---

# Top SHA256 hashes by process executions (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START and action_process_image_sha256 != null
| comp count() as cnt, count_distinct(agent_hostname) as hosts by action_process_image_sha256, action_process_image_name
| sort desc cnt
| limit 10
```

## When to use

Most-executed binaries by hash. The SHA256 is reputation-lookup-ready (VT, ThreatGrid, internal allowlists). Pair with host-count for blast-radius assessment.

## Variations

_(No variations are documented for this entry.)_
