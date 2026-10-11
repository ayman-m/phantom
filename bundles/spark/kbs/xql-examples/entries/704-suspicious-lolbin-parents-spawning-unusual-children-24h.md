---
id: XQL-704-1ce9fa11
title: Suspicious LOLBin parents spawning unusual children (24h)
category: detection
dataset: xdr_data
tags:
  - filter
  - comp
  - sort
  - limit
  - xdr_data
  - process
  - lolbin
  - T1218
---

# Suspicious LOLBin parents spawning unusual children (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| filter lowercase(actor_process_image_name) in ("rundll32.exe", "regsvr32.exe", "mshta.exe", "wmic.exe", "certutil.exe", "bitsadmin.exe")
| comp count() as cnt by actor_process_image_name, action_process_image_name
| sort asc cnt
| limit 10
```

## When to use

Classic Living-Off-The-Land Binaries (LOLBins) — when these utilities spawn unusual children, it often indicates attacker abuse. Sort by ascending count to surface rare combinations first.

## Variations

_(No variations are documented for this entry.)_
