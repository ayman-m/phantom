---
id: XQL-200-50ff3455
title: Rare new services
category: investigation
dataset: xdr_data
tags:
  - filter
  - alter
  - fields
  - comp
  - sort
  - xdr_data
  - source:dataset
---

# Rare new services

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.EVENT_LOG and action_evtlog_event_id in (7045, 4697) // Filtering by windows event log and id either 7045 or 4697
 | alter Service_Name = arrayindex(regextract(action_evtlog_message, "Service Name.*?(\w+)\r\n"),0), Service_cmd = arrayindex(regextract(action_evtlog_message,"Service File Name.*?(\w.*)\r\n"),0), Service_type = arrayindex(regextract(action_evtlog_message,"Service Type.*?(\w.*)\r\n"),0), Service_start_type = arrayindex(regextract(action_evtlog_message,"Service Start Type.*?(\w.*)\r\n"),0), Service_account = arrayindex(regextract(action_evtlog_message,"Service Account.*?(\w.*)"),0) // Using regextract to get just a part of the full event log message into an array, then using arrayindex to take the first item in the array
 | filter Service_Name != "MpKslDrv" // Filtering our a service related to MS 
 | fields Service_Name, Service_cmd, Service_type, Service_start_type, Service_account, event_id // Selecting all the relevant fields
 | comp count(event_id) as counter by Service_Name, Service_cmd, Service_type, Service_start_type, Service_account // Counting how many times each service was installed
 | filter counter <= 5 // Filtering by 5 or less occurrences
 | sort desc counter // Sorting in descending order
```

## When to use

Display services that have been installed 5 times or fewer

## Variations

_(No variations are documented for this entry.)_
