---
id: XQL-194-56af8db0
title: Windows successful logins
category: investigation
dataset: xdr_data
tags:
  - filter
  - alter
  - fields
  - xdr_data
  - source:dataset
---

# Windows successful logins

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.EVENT_LOG and action_evtlog_event_id = 4624 // Filtering by windows event log and id 4624
 | alter Logon_Type = arrayindex(regextract(action_evtlog_message, "Logon Type:.*?(\d+)\r\n"),0), Domain = arrayindex(regextract(action_evtlog_message, "New Logon:\r\n.*\r\n.*\r\n.Account Domain:.*?(\w.*)\r\n"),0), Source_IP = arrayindex(regextract(action_evtlog_message, "Source Network Address:.*?(\d+\.\d+\.\d+\.\d+)\r\n"),0), Process_Name = arrayindex(regextract(action_evtlog_message, "Process Name:.*?(\w.*)\r\n"),0), Host_Name = arrayindex(regextract(action_evtlog_message, "Workstation Name:.*?(\w.*)\r\n"),0), User_Name = arrayindex(regextract(action_evtlog_message,"New Logon:\r\n.*\r\n.*?Account Name:.*?(\w.*?)\r\n"),0) // Using regextract to get just a part of the full event log message into an array, then using arrayindex to take the first item in the array
 | fields User_Name, Host_Name, Domain, Logon_Type, Source_IP, Process_Name // Select all the fields to show them
```

## When to use

Display parsed successful logins to Windows hosts, including the username, hostname, domain, source, process and login type

## Variations

_(No variations are documented for this entry.)_
