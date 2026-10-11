---
id: XQL-498-753a7228
title: PUA - Sysinternals Tools Execution
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
  - Registry
  - Misconfiguration
---

# PUA - Sysinternals Tools Execution

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4 and event_sub_type = 1
 | filter (action_registry_key_name contains "\Active Directory Explorer" OR action_registry_key_name contains "\Handle" OR action_registry_key_name contains "\LiveKd" OR action_registry_key_name contains "\Process Explorer" OR action_registry_key_name contains "\ProcDump" OR action_registry_key_name contains "\PsExec" OR action_registry_key_name contains "\PsLoglist" OR action_registry_key_name contains "\PsPasswd" OR action_registry_key_name contains "\SDelete" OR action_registry_key_name contains "\Sysinternals") AND (action_registry_key_name ~= ".*\\EulaAccepted")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name
```

## When to use

Detects the execution of some potentially unwanted tools such as PsExec, Procdump, etc. (part of the Sysinternals suite) via the creation of the accepteula registry key.

## Variations

_(No variations are documented for this entry.)_
