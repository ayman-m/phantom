---
id: XQL-524-e1f5f55d
title: Shell Open Registry Keys Manipulation
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

# Shell Open Registry Keys Manipulation

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4
 | filter (action_registry_key_name ~= ".*Classes\\ms-settings\\shell\\open\\command\\SymbolicLinkValue") AND (action_registry_value_name contains "\Software\Classes\{") or (action_registry_key_name ~= ".*Classes\\ms-settings\\shell\\open\\command\\DelegateExecute") or ((action_registry_key_name ~= ".*Classes\\ms-settings\\shell\\open\\command\\(Default)" OR action_registry_key_name ~= ".*Classes\\exefile\\shell\\open\\command\\(Default)") and not (action_registry_value_name IN ("(Empty)")))
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name, action_registry_value_name
```

## When to use

Detects the shell open key manipulation (exefile and ms-settings) used for persistence and the pattern of UAC Bypass using fodhelper.exe, computerdefaults.exe, slui.exe via registry keys (e.g. UACMe 33 or 62).

## Variations

_(No variations are documented for this entry.)_
