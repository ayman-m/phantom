---
id: XQL-497-b52f108d
title: Suspicious Execution Of Renamed Sysinternals Tools
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

# Suspicious Execution Of Renamed Sysinternals Tools

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4 and event_sub_type = 1
 | filter (action_registry_key_name contains "\Active Directory Explorer" OR action_registry_key_name contains "\Handle" OR action_registry_key_name contains "\LiveKd" OR action_registry_key_name contains "\ProcDump" OR action_registry_key_name contains "\Process Explorer" OR action_registry_key_name contains "\PsExec" OR action_registry_key_name contains "\PsLoggedon" OR action_registry_key_name contains "\PsLoglist" OR action_registry_key_name contains "\PsPasswd" OR action_registry_key_name contains "\PsPing" OR action_registry_key_name contains "\PsService" OR action_registry_key_name contains "\SDelete") AND (action_registry_key_name ~= ".*\\EulaAccepted") and not (actor_process_image_path ~= ".*\\ADExplorer.exe" OR actor_process_image_path ~= ".*\\ADExplorer64.exe" OR actor_process_image_path ~= ".*\\handle.exe" OR actor_process_image_path ~= ".*\\handle64.exe" OR actor_process_image_path ~= ".*\\livekd.exe" OR actor_process_image_path ~= ".*\\livekd64.exe" OR actor_process_image_path ~= ".*\\procdump.exe" OR actor_process_image_path ~= ".*\\procdump64.exe" OR actor_process_image_path ~= ".*\\procexp.exe" OR actor_process_image_path ~= ".*\\procexp64.exe" OR actor_process_image_path ~= ".*\\PsExec.exe" OR actor_process_image_path ~= ".*\\PsExec64.exe" OR actor_process_image_path ~= ".*\\PsLoggedon.exe" OR actor_process_image_path ~= ".*\\PsLoggedon64.exe" OR actor_process_image_path ~= ".*\\psloglist.exe" OR actor_process_image_path ~= ".*\\psloglist64.exe" OR actor_process_image_path ~= ".*\\pspasswd.exe" OR actor_process_image_path ~= ".*\\pspasswd64.exe" OR actor_process_image_path ~= ".*\\PsPing.exe" OR actor_process_image_path ~= ".*\\PsPing64.exe" OR actor_process_image_path ~= ".*\\PsService.exe" OR actor_process_image_path ~= ".*\\PsService64.exe" OR actor_process_image_path ~= ".*\\sdelete.exe")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name
```

## When to use

Detects the creation of the accepteula key related to the Sysinternals tools being created from executables with the wrong name (e.g. a renamed Sysinternals tool).

## Variations

_(No variations are documented for this entry.)_
