---
id: XQL-167-b834cf65
title: RDP Failed Logins
category: investigation
dataset: xdr_login_events
tags:
  - preset
  - filter
  - fields
  - transaction
  - alter
  - xdr_login_events
  - source:preset
---

# RDP Failed Logins

**Dataset**: `xdr_login_events`

```sql
preset = xdr_login_events 
| filter outcome = "FAILURE"
| fields agent_hostname, action_local_ip , action_country , actor_process_image_name , event_type , action_user_status , outcome , outcome_reason , src_user , src_domain , dst_user , dst_domain
| transaction agent_hostname , action_local_ip maxevents = 2
| alter action_country = json_extract_scalar(arrayindex(_raw, 0), "$.action_country")
| alter action_process = json_extract_scalar(arrayindex(_raw, 0), "$.actor_process_image_name")
```

## When to use

RDP Failed Logins. Queries the `xdr_login_events` preset, filtered on `outcome = "FAILURE"`. Uses stages: `preset`, `filter`, `fields`, `transaction`, `alter`.

## Variations

_(No variations are documented for this entry.)_
