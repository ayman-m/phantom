---
id: XQL-243-53d7dbd7
title: Solarwinds Infected process executing WMI queries
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
---

# Solarwinds Infected process executing WMI queries

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // go over XDR data
|filter action_rpc_func_str_call_fields  != null // filter wmi queries
|filter lowercase(actor_process_image_name) = "solarwinds.businesslayerhost*.exe" // filter only the known solarwinds infected binary
|fields agent_hostname, action_rpc_func_str_call_fields // show the host and query
```

## When to use

Displays WMI queries done by the infected solarwinds binary

## Variations

_(No variations are documented for this entry.)_
