---
id: XQL-737-6a0c4016
title: Rare process executions — seen fewer than 5 times (24h)
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
---

# Rare process executions — seen fewer than 5 times (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| comp count() as cnt by action_process_image_name, actor_process_image_name
| filter cnt < 5
| sort asc cnt
| limit 10
```

## When to use

Rare-execution baseline anomaly detection. Process pairs seen fewer than 5 times in the timeframe are surfacing candidates. Two-stage comp + filter is the canonical rarity pattern.

## Variations

_(No variations are documented for this entry.)_
