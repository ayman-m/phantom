---
id: XQL-179-50998052
title: QR - Aggregated Network Traffic Destinations executed on DC
category: detection
dataset: xdr_data
tags:
  - filter
  - alter
  - fields
  - comp
  - join
  - xdr_data
  - source:dataset
  - quickwin
  - domain-controllers
  - ca_external_traffic_on_dc
  - windows
  - edr
  - medfi
  - irko
  - panwopen
  - poc
  - dashboard
---

# QR - Aggregated Network Traffic Destinations executed on DC

**Dataset**: `xdr_data`

```sql
// Description: Aggregated Network Traffic Destinations (EXTERNAL ONLY) (All Processes) executed on Domain Controllers
// Dataset: xdr_data, network
//Tags: QuickWin,domain-controllers,CA_external_traffic_on_dc,Windows,EDR,MedFi,IRKO,PANWOpen,POC,Dashboard

//Disable case sensitivity, last 30 days
config case_sensitive = false timeframe=30d

| dataset = xdr_data
| filter event_type = NETWORK 

// Filter out internal destinations =====
| filter  action_remote_ip != "10.*" and action_remote_ip != "192.168.*"
| alter rfc1918_172 = incidr(action_remote_ip, "172.16.0.0/12")
| filter rfc1918_172 = false
// ======================================

| fields event_timestamp, agent_hostname as Hostname, agent_ip_addresses as Agent_IP_Address, actor_effective_username as Username, actor_process_image_sha256 as Process_SHA256, actor_process_image_name as Process_Name, actor_process_image_path as Process_Path, action_external_hostname, action_local_ip, action_remote_ip, action_upload, action_download, event_type, event_sub_type
// | comp count(event_timestamp) as brower_process_event_count by Hostname, Browser_Process_Name

| join conflict_strategy = right type=right 
    (
        dataset = xdr_data
        | filter (event_type = EVENT_LOG and (action_evtlog_event_id = 4768))
        // Event 4768 only generates on domain controllers
        | comp count(event_timestamp) as kerberos_evtlog_4768_count by action_evtlog_event_id, agent_hostname
    ) as dc_list dc_list.agent_hostname = Hostname 
| filter Process_Name != null
| alter evtlog_id_4768_present = "TRUE"
    // ###### Modify Input Fields
    // Change "action_remote_ip" to the desired IP address field you wish to enrich/filter on
    | alter cmpnt_input_ip_addr = action_remote_ip

    // Component logic 
    | alter cmpnt_output_dest_is_internal = if(cmpnt_input_ip_addr ~= "^10[.].*" or cmpnt_input_ip_addr ~= "^192[.]168[.].*", "true", "false")
    | alter rfc1918_172 = incidr(cmpnt_input_ip_addr, "172.16.0.0/12")
    | alter cmpnt_output_dest_is_internal = if(cmpnt_output_dest_is_internal = "false" and rfc1918_172 = false, "false", "true")

    // Optional Filter to remove results with internal (private) ip addresses
    //| filter cmpnt_output_dest_is_internal = "false"

    // ###### Modify Output Fields
    | alter dest_is_internal = cmpnt_output_dest_is_internal

// #### End: Internal/External IP component 
| fields event_timestamp, Hostname, Agent_IP_Address, Username, Process_SHA256, Process_Name, Process_Path, action_external_hostname, action_local_ip, action_remote_ip, action_upload, action_download, event_type, event_sub_type, dest_is_internal
// | fields agent_hostname, evtlog_id_4768_present, kerberos_evtlog_4768_count, Browser_Process_Name, brower_process_event_count
// | comp count_distinct(agent_hostname) by Browser_Process_Name 
| comp count(event_timestamp) as connection_count, max(event_timestamp) as lastTime, values(action_external_hostname) as external_hostnames, values(Username) as users, values(Process_Name) as Processes, sum(action_upload) as bytes_uploaded, sum(action_download) as bytes_downloaded by Hostname, action_remote_ip, dest_is_internal
| alter lTime  = to_timestamp(lastTime, "millis"), dSource = "XDR - Network", Notes = "External Network Connections from Domain Controller", rCatagory = "Risky Configuration"
|fields Hostname, users, Processes, external_hostnames, action_remote_ip, dest_is_internal, lTime, connection_count, bytes_uploaded, bytes_downloaded, dSource, Notes, rCatagory
```

## When to use

Aggregated Network Traffic Destinations (EXTERNAL ONLY) (All Processes) executed on Domain Controllers

## Variations

_(No variations are documented for this entry.)_
