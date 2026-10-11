---
id: XQL-182-4685829c
title: QR - Clearing Windows EventLog
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
  - windows
  - lowfi
  - ca_event_logs
  - panwopen
---

# QR - Clearing Windows EventLog

**Dataset**: `forensics_event_log`

```sql
// Title: Windows_EventLog_Clearing
// Description: Dataset Query - this will return events associated with Windows Event Log Clearing
// Dataset: forensics_event_log
// Requirements: Events are collected through search collections or triage
// Filter: None
//Tags: Windows,LowFi,CA_event_logs,PANWOpen

//######NOTES######: 
// BUG - XDR is not capturing the message field for System event 104
// You'll need to reference the evtx file for the specific channel that was cleared

//Disable case sensitivity, last 30 days
config case_sensitive = false timeframe=30d

// Use the forensics_event_log dataset
| dataset = forensics_event_log 

// Filter here for Host_Name

// Filter for Microsoft-Windows-Eventlog events, System Event ID 104 and Security Event ID 1102
| filter provider = "Microsoft-Windows-Eventlog" and (source = "System" and event_id = 104 or (source = "Security" and event_id in (517,1102)))

// Extract fields from message (applicable to event_id 1102 only)
| alter User_SID = if (event_id = 1102 and search_uuid != null, arrayindex(regextract(message,"Security ID:\t+(.*)\r\n\t"),0),
        if (event_id = 1102 and search_uuid = null, arrayindex(regextract(message,"UserSid=(.*)\n"),0), "N/A")),
    User_Name = if (event_id = 1102 and search_uuid != null, arrayindex(regextract(message,"Account Name:\t+(.*)\r\n\t"),0),
        if (event_id = 1102 and search_uuid = null, arrayindex(regextract(message,"UserName=(.*)\n"),0), "N/A")),
    Domain_Name = if (event_id = 1102 and search_uuid != null, arrayindex(regextract(message,"Domain Name:\t+(.*)\r\n\t"),0),
        if (event_id = 1102 and search_uuid = null, arrayindex(regextract(message,"DomainName=(.*)\n"),0), "N/A")),
    Logon_ID = if (event_id = 1102 and search_uuid != null, arrayindex(regextract(message,"Logon ID:\t+(.*)"),0),
        if (event_id = 1102 and search_uuid = null, arrayindex(regextract(message,"LogonId=(.*)"),0), "N/A"))

// Create Timestamp field, add event description
| alter Timestamp = to_timestamp(event_generated, "millis"),
    Event_Description = if (event_id in (517,1102), "The audit log was cleared", if (event_id = 104, "A log file was cleared - reference EVTX file for Channel","N/A"))

// Return Relevant Fields
| fields Timestamp, host_name, source, event_id, provider, Event_Description, User_SID, User_Name, Domain_Name, Logon_ID, message 

// Sort by Timestamp descending
| sort desc Timestamp 


// Use this comp line to combine entries that share the same service name, host name, and user. This will return the latest timestamp entry
/*| comp  max(Timestamp) as _timestamp, max(message) as _messages, count(event_id) as _count by Service_Name, host_name, User_Name,event_id, source, Event_Description
| alter xtra = concat("event count:", to_string(_count)), Discovery_Source="Forensics - Event Logs"
| fields host_name, event_id, source, _timestamp, User_Name, _message, xtra, Discovery_Source, Event_Description */
```

## When to use

Dataset Query - this will return events associated with Windows Event Log Clearing

## Variations

_(No variations are documented for this entry.)_
