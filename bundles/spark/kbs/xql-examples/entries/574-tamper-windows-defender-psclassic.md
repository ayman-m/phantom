---
id: XQL-574-a17b5a14
title: Tamper Windows Defender - PSClassic
category: investigation
dataset: xdr_data
tags:
  - filter
  - alter
  - fields
  - xdr_data
  - source:dataset
  - PowerShell
---

# Tamper Windows Defender - PSClassic

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter (event_type = 31 and event_sub_type = 10) or (event_type = 15 and action_evtlog_event_id IN (4104)) | alter script_data = if (event_type = 15, action_evtlog_message , to_string(dynamic_event_string_map))
| filter (script_data contains "Set-MpPreference") and (((script_data contains "-dbaf $true" OR  script_data contains "-dbaf 1" OR  script_data contains "-dbm $true" OR  script_data contains "-dbm 1" OR  script_data contains "-dips $true" OR  script_data contains "-dips 1" OR  script_data contains "-DisableArchiveScanning $true" OR  script_data contains "-DisableArchiveScanning 1" OR  script_data contains "-DisableBehaviorMonitoring $true" OR  script_data contains "-DisableBehaviorMonitoring 1" OR  script_data contains "-DisableBlockAtFirstSeen $true" OR  script_data contains "-DisableBlockAtFirstSeen 1" OR  script_data contains "-DisableCatchupFullScan $true" OR  script_data contains "-DisableCatchupFullScan 1" OR  script_data contains "-DisableCatchupQuickScan $true" OR  script_data contains "-DisableCatchupQuickScan 1" OR  script_data contains "-DisableIntrusionPreventionSystem $true" OR  script_data contains "-DisableIntrusionPreventionSystem 1" OR  script_data contains "-DisableIOAVProtection $true" OR  script_data contains "-DisableIOAVProtection 1" OR  script_data contains "-DisableRealtimeMonitoring $true" OR  script_data contains "-DisableRealtimeMonitoring 1" OR  script_data contains "-DisableRemovableDriveScanning $true" OR  script_data contains "-DisableRemovableDriveScanning 1" OR  script_data contains "-DisableScanningMappedNetworkDrivesForFullScan $true" OR  script_data contains "-DisableScanningMappedNetworkDrivesForFullScan 1" OR  script_data contains "-DisableScanningNetworkFiles $true" OR  script_data contains "-DisableScanningNetworkFiles 1" OR  script_data contains "-DisableScriptScanning $true" OR  script_data contains "-DisableScriptScanning 1" OR  script_data contains "-MAPSReporting $false" OR  script_data contains "-MAPSReporting 0" OR  script_data contains "-drdsc $true" OR  script_data contains "-drdsc 1" OR  script_data contains "-drtm $true" OR  script_data contains "-drtm 1" OR  script_data contains "-dscrptsc $true" OR  script_data contains "-dscrptsc 1" OR  script_data contains "-dsmndf $true" OR  script_data contains "-dsmndf 1" OR  script_data contains "-dsnf $true" OR  script_data contains "-dsnf 1" OR  script_data contains "-dss $true" OR  script_data contains "-dss 1")) OR ((script_data contains "HighThreatDefaultAction Allow" OR  script_data contains "htdefac Allow" OR  script_data contains "LowThreatDefaultAction Allow" OR  script_data contains "ltdefac Allow" OR  script_data contains "ModerateThreatDefaultAction Allow" OR  script_data contains "mtdefac Allow" OR  script_data contains "SevereThreatDefaultAction Allow" OR  script_data contains "stdefac Allow")))
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, script_data
```

## When to use

Detect attempts to disable scheduled scanning and other parts of Windows Defender ATP or set default actions to allow.

## Variations

_(No variations are documented for this entry.)_
