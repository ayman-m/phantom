---
id: XQL-590-658558fd
title: DSInternals Suspicious PowerShell Cmdlets - ScriptBlock
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

# DSInternals Suspicious PowerShell Cmdlets - ScriptBlock

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter (event_type = 31 and event_sub_type = 10) or (event_type = 15 and action_evtlog_event_id IN (4104)) | alter script_data = if (event_type = 15, action_evtlog_message , to_string(dynamic_event_string_map))
| filter (script_data contains "Add-ADDBSidHistory" OR  script_data contains "Add-ADNgcKey" OR  script_data contains "Add-ADReplNgcKey" OR  script_data contains "ConvertFrom-ADManagedPasswordBlob" OR  script_data contains "ConvertFrom-GPPrefPassword" OR  script_data contains "ConvertFrom-ManagedPasswordBlob" OR  script_data contains "ConvertFrom-UnattendXmlPassword" OR  script_data contains "ConvertFrom-UnicodePassword" OR  script_data contains "ConvertTo-AADHash" OR  script_data contains "ConvertTo-GPPrefPassword" OR  script_data contains "ConvertTo-KerberosKey" OR  script_data contains "ConvertTo-LMHash" OR  script_data contains "ConvertTo-MsoPasswordHash" OR  script_data contains "ConvertTo-NTHash" OR  script_data contains "ConvertTo-OrgIdHash" OR  script_data contains "ConvertTo-UnicodePassword" OR  script_data contains "Disable-ADDBAccount" OR  script_data contains "Enable-ADDBAccount" OR  script_data contains "Get-ADDBAccount" OR  script_data contains "Get-ADDBBackupKey" OR  script_data contains "Get-ADDBDomainController" OR  script_data contains "Get-ADDBGroupManagedServiceAccount" OR  script_data contains "Get-ADDBKdsRootKey" OR  script_data contains "Get-ADDBSchemaAttribute" OR  script_data contains "Get-ADDBServiceAccount" OR  script_data contains "Get-ADDefaultPasswordPolicy" OR  script_data contains "Get-ADKeyCredential" OR  script_data contains "Get-ADPasswordPolicy" OR  script_data contains "Get-ADReplAccount" OR  script_data contains "Get-ADReplBackupKey" OR  script_data contains "Get-ADReplicationAccount" OR  script_data contains "Get-ADSIAccount" OR  script_data contains "Get-AzureADUserEx" OR  script_data contains "Get-BootKey" OR  script_data contains "Get-KeyCredential" OR  script_data contains "Get-LsaBackupKey" OR  script_data contains "Get-LsaPolicy" OR  script_data contains "Get-SamPasswordPolicy" OR  script_data contains "Get-SysKey" OR  script_data contains "Get-SystemKey" OR  script_data contains "New-ADDBRestoreFromMediaScript" OR  script_data contains "New-ADKeyCredential" OR  script_data contains "New-ADNgcKey" OR  script_data contains "New-NTHashSet" OR  script_data contains "Remove-ADDBObject" OR  script_data contains "Save-DPAPIBlob" OR  script_data contains "Set-ADAccountPasswordHash" OR  script_data contains "Set-ADDBAccountPassword" OR  script_data contains "Set-ADDBBootKey" OR  script_data contains "Set-ADDBDomainController" OR  script_data contains "Set-ADDBPrimaryGroup" OR  script_data contains "Set-ADDBSysKey" OR  script_data contains "Set-AzureADUserEx" OR  script_data contains "Set-LsaPolicy" OR  script_data contains "Set-SamAccountPasswordHash" OR  script_data contains "Set-WinUserPasswordHash" OR  script_data contains "Test-ADDBPasswordQuality" OR  script_data contains "Test-ADPasswordQuality" OR  script_data contains "Test-ADReplPasswordQuality" OR  script_data contains "Test-PasswordQuality" OR  script_data contains "Unlock-ADDBAccount" OR  script_data contains "Write-ADNgcKey" OR  script_data contains "Write-ADReplNgcKey")
| fields agent_hostname, event_type, event_sub_type, actor_process_image_path, actor_process_os_pid, actor_process_image_md5, actor_process_signature_vendor, actor_process_signature_status, actor_effective_username, script_data
```

## When to use

Detects execution and usage of the DSInternals PowerShell module.

## Variations

_(No variations are documented for this entry.)_
