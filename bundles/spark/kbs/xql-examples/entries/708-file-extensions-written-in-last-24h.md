---
id: XQL-708-bf3622c5
title: File extensions written in last 24h
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - sort
  - limit
  - xdr_data
  - file
---

# File extensions written in last 24h

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.FILE
| comp count() as cnt by action_file_extension
| sort desc cnt
| limit 10
```

## When to use

Aggregate file events by extension to baseline file-write patterns. Spikes in unusual extensions (.lnk, .scr, .ps1) can indicate attacker tooling drops.

## Variations

_(No variations are documented for this entry.)_
