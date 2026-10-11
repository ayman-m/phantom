---
id: XQL-759-7e45f632
title: Processes signed with non-Microsoft cert in System32 (24h, T1036.005)
category: detection
dataset: xdr_data
tags:
  - filter
  - fields
  - sort
  - limit
  - xdr_data
  - process
  - T1036.005
---

# Processes signed with non-Microsoft cert in System32 (24h, T1036.005)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START
| filter lowercase(action_process_image_path) contains "system32\\"
| filter action_process_signature_vendor != null and lowercase(action_process_signature_vendor) != "microsoft corporation"
| fields _time, agent_hostname, action_process_image_path, action_process_signature_vendor, action_process_signature_status
| sort desc _time
| limit 10
```

## When to use

Binaries running from System32 signed by a non-Microsoft vendor — MITRE T1036.005 (Match Legitimate Name or Location). High-fidelity masquerading indicator.

## Variations

_(No variations are documented for this entry.)_
