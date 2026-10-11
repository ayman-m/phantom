---
id: XQL-494-54cf6db8
title: Potential Persistence Via Disk Cleanup Handler
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

# Potential Persistence Via Disk Cleanup Handler

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4 and event_sub_type = 1
 | filter (action_registry_key_name contains "\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\VolumeCaches") and not (action_registry_key_name ~= ".*\\Active Setup Temp Folders" OR action_registry_key_name ~= ".*\\BranchCache" OR action_registry_key_name ~= ".*\\Content Indexer Cleaner" OR action_registry_key_name ~= ".*\\D3D Shader Cache" OR action_registry_key_name ~= ".*\\Delivery Optimization Files" OR action_registry_key_name ~= ".*\\Device Driver Packages" OR action_registry_key_name ~= ".*\\Diagnostic Data Viewer database files" OR action_registry_key_name ~= ".*\\Downloaded Program Files" OR action_registry_key_name ~= ".*\\DownloadsFolder" OR action_registry_key_name ~= ".*\\Feedback Hub Archive log files" OR action_registry_key_name ~= ".*\\Internet Cache Files" OR action_registry_key_name ~= ".*\\Language Pack" OR action_registry_key_name ~= ".*\\Microsoft Office Temp Files" OR action_registry_key_name ~= ".*\\Offline Pages Files" OR action_registry_key_name ~= ".*\\Old ChkDsk Files" OR action_registry_key_name ~= ".*\\Previous Installations" OR action_registry_key_name ~= ".*\\Recycle Bin" OR action_registry_key_name ~= ".*\\RetailDemo Offline Content" OR action_registry_key_name ~= ".*\\Setup Log Files" OR action_registry_key_name ~= ".*\\System error memory dump files" OR action_registry_key_name ~= ".*\\System error minidump files" OR action_registry_key_name ~= ".*\\Temporary Files" OR action_registry_key_name ~= ".*\\Temporary Setup Files" OR action_registry_key_name ~= ".*\\Temporary Sync Files" OR action_registry_key_name ~= ".*\\Thumbnail Cache" OR action_registry_key_name ~= ".*\\Update Cleanup" OR action_registry_key_name ~= ".*\\Upgrade Discarded Files" OR action_registry_key_name ~= ".*\\User file versions" OR action_registry_key_name ~= ".*\\Windows Defender" OR action_registry_key_name ~= ".*\\Windows Error Reporting Files" OR action_registry_key_name ~= ".*\\Windows ESD installation files" OR action_registry_key_name ~= ".*\\Windows Upgrade Log Files")
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name
```

## When to use

Detects when an attacker modifies values of the Disk Cleanup Handler in the registry to achieve persistence.

## Variations

_(No variations are documented for this entry.)_
