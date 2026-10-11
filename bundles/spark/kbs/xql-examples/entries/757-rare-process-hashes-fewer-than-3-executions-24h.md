---
id: XQL-757-8c8424a4
title: Rare process hashes — fewer than 3 executions (24h)
category: detection
dataset: xdr_data
tags:
  - filter
  - comp
  - sort
  - limit
  - xdr_data
  - process
  - rare
  - hash
---

# Rare process hashes — fewer than 3 executions (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START and action_process_image_sha256 != null
| comp count() as cnt by action_process_image_sha256, action_process_image_name
| filter cnt < 3
| sort asc cnt
| limit 10
```

## When to use

Rare-by-hash executions. New + unfamiliar binaries surface as low-count rows. The pattern relies on hash distinctiveness to catch packed/repacked malware that varies its filename.

## Variations

_(No variations are documented for this entry.)_
