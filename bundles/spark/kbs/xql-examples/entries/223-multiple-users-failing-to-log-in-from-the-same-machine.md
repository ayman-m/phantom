---
id: XQL-223-bf0f824f
title: Multiple users failing to log in from the same machine
category: investigation
dataset: xdr_data
tags:
  - filter
  - alter
  - comp
  - sort
  - xdr_data
  - source:dataset
---

# Multiple users failing to log in from the same machine

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.EVENT_LOG and action_evtlog_event_id = 4625 and agent_hostname != null // Filtering by windows event log and id 4625 that came from an XDR agent
 | alter User_Name = arrayindex(regextract(action_evtlog_message, "Account For Which Logon Failed:\r\n.*\r\n.*Account Name:.*?(\w.*)\r\n"),0), Host_Name = arrayindex(regextract(action_evtlog_message, "Workstation Name:.*?(\w.*)\r\n"),0) // Using regextract to get just a part of the full event log message into an array, then using arrayindex to take the first item in the array
 | comp count_distinct(User_Name) as Counter by Host_Name // Counting unique users who failed to authenticate on a host
 | filter Counter >= 5 and Host_Name != null // Filtering by 5 or more unique users per host and where hostname != null
 | sort desc Counter // Sorting in descending order
```

## When to use

Display cases where 5 or more users failed to authenticate on the same host, which could be an indication of brute force attack

## Variations

_(No variations are documented for this entry.)_
