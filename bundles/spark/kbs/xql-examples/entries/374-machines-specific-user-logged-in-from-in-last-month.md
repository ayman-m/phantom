---
id: XQL-374-037cdccf
title: Machines Specific User Logged in from in Last Month
category: investigation
dataset: xdr_data
tags:
  - config
  - filter
  - alter
  - comp
  - xdr_data
  - source:dataset
---

# Machines Specific User Logged in from in Last Month

**Dataset**: `xdr_data`

```sql
config timeframe = 30d |
dataset = xdr_data
| filter event_type = EVENT_LOG | filter action_evtlog_event_id = 4624
| alter user_name = arrayindex(regextract(action_evtlog_message,"Account\sName\:\t\t(\S+)"),1)
| filter user_name contains $user
| alter logon_process = arrayindex(regextract(action_evtlog_message, "Logon\sProcess:\t\t(\S+)"),0)
| alter logon_type = arrayindex(regextract(action_evtlog_message, "Logon\sType:\t\t(\d+)"),0)
| alter security_id = arrayindex(regextract(action_evtlog_message, "Security\sID:\t\t(\S+)"),0)
| alter account_name = arrayindex(regextract(action_evtlog_message, "Account\sName:\t\t(\S+)"),0)
| alter account_domain = arrayindex(regextract(action_evtlog_message, "Account\sDomain\:\t\t(\S+)"),0)
| alter network_address = arrayindex(regextract(action_evtlog_message, "Network\sAddress:\t(\S+)") ,0)
| alter workstation_name = arrayindex(regextract(action_evtlog_message, "Workstation\sName\:\t(\S+)"),0)
| alter host_name = coalesce(account_name,workstation_name )
| filter (host_name != "-" and network_address != "-")
| filter host_name != null
| comp count_distinct(host_name), values(host_name) as hosts, values(network_address) as ip by user_name
```

## When to use

Filters by event ID 4624 and then aggregates all the information related to the hostname and IP addresses for a specified user from the last month

## Variations

_(No variations are documented for this entry.)_
