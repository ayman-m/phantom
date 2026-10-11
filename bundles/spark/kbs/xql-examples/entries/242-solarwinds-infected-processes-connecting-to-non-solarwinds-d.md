---
id: XQL-242-8c36dff6
title: Solarwinds infected processes connecting to non solarwinds domains
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - dedup
  - xdr_data
  - source:dataset
---

# Solarwinds infected processes connecting to non solarwinds domains

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // go over xdr data
|filter event_type = ENUM.NETWORK  // go over agent network events
|filter lowercase(actor_process_image_name) = "solarwinds.businesslayerhost*.exe"  // filter only the infected solarwinds executables
|filter  action_external_hostname not contains "solarwinds.com" and action_external_hostname != "*.local" // select non local non solarwinds domains
|fields causality_actor_process_image_path, actor_process_image_path, agent_hostname, action_remote_ip, action_external_hostname // select presentation fields
|dedup causality_actor_process_image_path, actor_process_image_path, agent_hostname, action_remote_ip, action_external_hostname // dedup to reduce noise
```

## When to use

Displays network communication with non solarwinds domains by the solarwinds infected process

## Variations

_(No variations are documented for this entry.)_
