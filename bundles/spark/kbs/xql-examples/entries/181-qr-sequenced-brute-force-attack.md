---
id: XQL-181-3cf30044
title: QR - Sequenced Brute Force Attack
category: detection
dataset: xdr_data
tags:
  - filter
  - alter
  - bin
  - comp
  - sort
  - join
  - fields
  - xdr_data
  - source:dataset
  - hunt-demo
---

# QR - Sequenced Brute Force Attack

**Dataset**: `xdr_data`

```sql
//Title: Sequenced Brute Force Attack
///Description: Mitre Query - This query looks for patterns of brute force attacks in event logs
//Tactic: TA0006 Credential Access
//Technique(s): T1110.0004 - Brute Force
//Tags: EDR,Windows,LowFi,IRKO,PANWOpen,POC,Dashboard

//Turns off case sensitivity and sets timeframe to 30 days 
config case_sensitive = false timeframe = 30d


//Section One - Logon Failures
| dataset = xdr_data
//Use the forensics_event_log dataset
|filter event_type=ENUM.EVENT_LOG AND action_evtlog_event_id = 4625

|alter WorkstationName = trim(json_extract(action_evtlog_data_fields,"$.WorkstationName"),"\"")
|alter WorkstationName = uppercase(WorkstationName)
|alter Logon_Type = trim(json_extract(action_evtlog_data_fields,"$.LogonType"),"\"")
|alter Ip_Address = trim(json_extract(action_evtlog_data_fields,"$.IpAddress"),"\"")
|alter TargetDomainName = trim(json_extract(action_evtlog_data_fields,"$.TargetDomainName"),"\"")
|alter Target_User_Name = trim(json_extract(action_evtlog_data_fields,"$.TargetUserName"),"\"")
|alter event_generated1 = to_timestamp(event_timestamp, "millis")
|alter eventDay = extract_time(event_generated1 , "DAYOFYEAR"), eventHour = extract_time(event_generated1, "HOUR")
|alter Failure_Reason = trim(json_extract(action_evtlog_data_fields,"$.FailureReason"),"\"")


//Filter for noninteractive/interactive remote logon events and remove null usernames
| filter Logon_Type in ("3", "10") and IP_Address not in("","-","LOCAL", "127.0.0.1", "::1") and Target_User_Name not in (" ","") and Target_User_Name not contains "$"

//Interpret %%2313 failure reason
| alter Failure_Reason = if (Failure_Reason = "%%2313", "Unknown user name or bad password", Failure_Reason)
| alter Failure_Reason = if (Failure_Reason = "%%2307", "Account locked out", Failure_Reason)
| alter Failure_Reason = if (Failure_Reason = "%%2308", "The user has not been granted the requested logon type at this machine", Failure_Reason)
| alter Failure_Reason = if (Failure_Reason = "%%2309", "The specified account's password has expired.", Failure_Reason)
| alter Failure_Reason = if (Failure_Reason = "%%2310", "Account currently disabled", Failure_Reason)

|bin _time span=24

//Compute failure count by host and user by the hour
| comp count() as failCount, max(event_generated1) as lastFail, min(event_generated1) as firstFail, values(Failure_Reason) as Failure_Reason, count_distinct(Target_User_Name) as fail_unique_username_count, values(agent_hostname) as fail_target_host_name, count_distinct(agent_hostname) as fail_unique_target_host_name_count, count_distinct(IP_Address) by Target_User_Name, Logon_Type, Ip_Address 

// Adjust Filter based on the failcount 
| filter failCount > 5

| sort desc failCount 
| join type= inner 
(dataset = xdr_data
|filter event_type=ENUM.EVENT_LOG AND action_evtlog_event_id = 4624
|alter WorkstationName = trim(json_extract(action_evtlog_data_fields,"$.WorkstationName"),"\"")
|alter WorkstationName = uppercase(WorkstationName)
|alter Logon_Type = trim(json_extract(action_evtlog_data_fields,"$.LogonType"),"\"")
|alter Ip_Address = trim(json_extract(action_evtlog_data_fields,"$.IpAddress"),"\"")
|alter TargetDomainName = trim(json_extract(action_evtlog_data_fields,"$.TargetDomainName"),"\"")
|alter Target_User_Name = trim(json_extract(action_evtlog_data_fields,"$.TargetUserName"),"\"")
|alter event_generated1 = to_timestamp(event_timestamp, "millis")
|alter eventDay = extract_time(event_generated1 , "DAYOFYEAR"), eventHour = extract_time(event_generated1, "HOUR")


//Filter for noninteractive/interactive remote logon events and remove null usernames
| filter Logon_Type in ("3", "10") and IP_Address not in("","-","LOCAL", "127.0.0.1", "::1") and Target_User_Name not in (" ","") and Target_User_Name not contains "$"
|bin _time span=24h

//Compute failure count by host and user by the hour
| comp count() as successCount, max(event_generated1) as lastSuccess, min(event_generated1) as firstSuccess, count_distinct(IP_Address) as Success_src_ip, count_distinct(Target_User_Name) as Success_unique_username_count, values(agent_hostname) as Success_target_host_name, count_distinct(agent_hostname) as Success_unique_target_host_name_count by Target_User_Name, Logon_Type) as success success.firstSuccess > lastFail and success.Target_User_Name = Target_User_Name 



//Use the following sections for IR and CA engagements (Keep comp lines above On for this sections)
//Returning relevant fields
//| filter IP_Address in ("[Finding]", "[Finding]")
//| filter target_user_name in ("[Finding]", "[Finding]")
//| filter fail_target_host_name in ("[Finding]", "[Finding]")
//| fields Ip_Address, target_user_name, firstSuccess, lastSuccess, successCount, fail_target_host_name, firstFail, lastFail, failCount

//Use this section to aggregate data for CA analysis, turn off for reporting (Keep all comp lines for original query turned ON for this sections)
//1st pass
//| filter IP_Address in ("[Finding]", "[Finding]")
//| filter fail_target_host_name ("[Finding]", "[Finding]")
//| comp count(Ip_Address) as total by Ip_Address, failCount  
//| sort desc failCount

//Use this section to put finding in report format for CA, replace [Finding] with what you would like to report (wildcards* accepted), field for filtering can be changed
// (Keep all comp/field lines for orginal qurey turned ON for this sections)
//| filter Source_Address in ("[Finding]", "[Finding]")
//| filter Target_User_Name ("[Finding]", "[Finding]")
//| alter disc_source = "Forensics Event Logs"
//| alter dif= timestamp_diff(lastFail, firstFail, "DAY" )
//| alter event_id = "4625" 
//| fields Target_User_Name, dif,  IP_Address, fail_target_host_name, Logon_Type, event_id, lastFail, Failure_Reason, disc_source
//| sort desc lastFail
```

## When to use

Sequenced Brute Force Attack. Queries the `xdr_data` dataset directly, filtered on `event_type=ENUM.EVENT_LOG AND action_evtlog_event_id = 4625`. Uses stages: `filter`, `alter`, `bin`, `comp`, `sort`, `join`.

## Variations

_(No variations are documented for this entry.)_
