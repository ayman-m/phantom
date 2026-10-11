---
id: XQL-715-309d319b
title: Top registry keys modified (24h)
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - sort
  - limit
  - xdr_data
  - registry
---

# Top registry keys modified (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.REGISTRY
| comp count() as modifications by action_registry_key_name
| sort desc modifications
| limit 10
```

## When to use

Most-modified registry keys baseline. Windows housekeeping dominates; spikes in autoruns / boot-execute / image-file-execution paths are persistence indicators.

## Variations

_(No variations are documented for this entry.)_
