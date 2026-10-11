---
id: XQL-503-e1c6c257
title: Removal of Potential COM Hijacking Registry Keys
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

# Removal of Potential COM Hijacking Registry Keys

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
 | filter event_type = 4 and event_sub_type = 2
 | filter (action_registry_key_name ~= ".*\\shell\\open\\command") and not (((actor_process_image_path IN ("C:\Windows\system32\svchost.exe"))) OR ((actor_process_image_path ~= "C:\\Program Files\\Common Files\\Microsoft Shared\\ClickToRun\\.*" OR actor_process_image_path ~= "C:\\Program Files\\Common Files\\Microsoft Shared\\ClickToRun\\Updates\\.*") AND (actor_process_image_path ~= ".*\\OfficeClickToRun.exe")) OR ((actor_process_image_path IN ("C:\Program Files (x86)\Microsoft Office\root\integration\integrator.exe"))) OR ((actor_process_image_path ~= ".*\\Dropbox.exe") AND (action_registry_key_name contains "\Dropbox.")) OR ((actor_process_image_path ~= ".*\\AppData\\Local\\Temp\\Wireshark_uninstaller.exe") AND (action_registry_key_name contains "\wireshark-capture-file")) OR ((actor_process_image_path ~= "C:\\Program Files\\Opera\\.*" OR actor_process_image_path ~= "C:\\Program Files (x86)\\Opera\\.*") AND (actor_process_image_path ~= ".*\\installer.exe")) OR ((actor_process_image_path contains "peazip") AND (action_registry_key_name contains "\PeaZip.")) OR ((actor_process_image_path ~= ".*\\Everything.exe") AND (action_registry_key_name contains "\Everything.")) OR ((actor_process_image_path ~= "C:\\Windows\\Installer\\MSI.*")) OR ((actor_process_image_path ~= "C:\\Program Files (x86)\\Java\\.*") AND (actor_process_image_path ~= ".*\\installer.exe") AND (action_registry_key_name contains "\Classes\WOW6432Node\CLSID\{4299124F-F2C3-41b4-9C73-9236B2AD0E8F}")))
 | fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, action_registry_key_name
```

## When to use

Detects any deletion of entries in .*\shell\open\command registry keys.

## Variations

_(No variations are documented for this entry.)_
