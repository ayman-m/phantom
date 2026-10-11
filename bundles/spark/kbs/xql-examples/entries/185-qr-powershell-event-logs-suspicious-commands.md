---
id: XQL-185-6a798ea4
title: QR - PowerShell Event Logs Suspicious Commands
category: detection
dataset: forensics_event_log
tags:
  - filter
  - alter
  - fields
  - sort
  - comp
  - forensics_event_log
  - source:dataset
  - ca_event_logs
  - windows
  - medfi
  - irko
  - panwopen
  - poc
---

# QR - PowerShell Event Logs Suspicious Commands

**Dataset**: `forensics_event_log`

```sql
//Title: PowerShell_Event_Logs_Suspicious_Commands
//Description: Query searches all Powershell logs in the forensic event log dataset for suspicious keywords
//Dataset: forensics_event_log
//Requirements: Systems must be in an agent policy with XDR pro endpoints and monitor and collect forensics data enabled.  Additionally, Powershell event logs must be pre-populated for this search to work.  Event logs needed for this query can be pre-populated by enabling all of the search collections in the agent profile or by doing a forensics event log search from the action center search prior to running this query. 
//Filter: Filters message field for suspicious keywords, filters the source field to include any log channels with the word powershell
//Tags: CA_event_logs,Windows,MedFi,IRKO,PANWOpen,POC

//Disable case sensitivity, last 30 days
config case_sensitive = false timeframe=30d

// Use the forensics event log dataset 
|dataset = forensics_event_log 

// Filter the event log channel for any log containing powershell
| filter source in ("Windows PowerShell", "Microsoft-Windows-PowerShell/Operational")

// Filter the message field for suspcious powershell keywords 
| filter message ~= "(-enc\s|downloadstring|base64|-w\shidden|comspec|webclient|virtualalloc|io.memorystream|IEX\()"

//Extract the HostApplication value from the message field and place it in a new field titled host_application
| alter Host_Application = if (search_uuid != null, arrayindex(regextract(message, "HostApplication=(.*)\r\n\tEngine"),0), arrayindex(regextract(message, "HostApplication=(.*)\n\tEngine"),0))

// Create new timestamp field using existing event_generated field
| alter timestamp = to_timestamp(event_generated , "millis") 

// Select most useful fields 
| fields timestamp, host_name, event_id , source , user, Host_application , message 

// Sort output by timestamp field 
| sort desc timestamp 

/*
// filter the common noisy microsoft tooling
| filter message not contains "Windows Defender Advanced Threat Protection"
| filter message not contains "Microsoft.AdminCenter.AdminCenter"
| filter message not contains "Microsoft Dependency Agent"
| filter message not contains "Microsoft Azure AD Sync"
*/

//Use this section to put findings in report format for CA, turn on and off individual filters to minimize data
/*| alter Discovery_Source = "Forensics - Event Logs"
| filter (Host_Application = "[Finding]")
 | comp count(event_id) as _count,  max(timestamp) as timestamp,  max(message) as _message by host_name, Host_Application,event_id, source, user
 | sort asc timestamp
 | alter xtra = concat("event count:", to_string(_count)), discoverysource = "Forensics - Event Logs"
 | fields host_name, event_id, source, timestamp, user, _message, xtra, discoverysource  */
```

## When to use

Query searches all Powershell logs in the forensic event log dataset for suspicious keywords

## Variations

_(No variations are documented for this entry.)_
