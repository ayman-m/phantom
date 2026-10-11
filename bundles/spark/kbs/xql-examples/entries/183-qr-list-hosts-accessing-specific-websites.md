---
id: XQL-183-75d99dc1
title: QR- List hosts accessing specific websites
category: detection
dataset: xdr_data
tags:
  - filter
  - alter
  - fields
  - limit
  - sort
  - comp
  - xdr_data
  - source:dataset
  - edr
  - allos
  - medfi
  - irko
  - panwopen
  - ca_network
---

# QR- List hosts accessing specific websites

**Dataset**: `xdr_data`

```sql
//Title: List hosts accessing specific websites
//Description: This query searches for hosts accessing certain sites. There are filters for some quick win hacking/lateral movement/exfil tools by default. Users can add specific IOCs as needed.
//Dataset: xdr_data events//Requirements: Endpoints must have the Cortex XDR agent installed, and events must have occurred since installation. Agent must have checked in (come online) since events occurred for events to appear in dataset.
//Tags: EDR,AllOS,MedFi,IRKO,PANWOpen, CA_Network

config case_sensitive = false timeframe = 30d
| dataset = xdr_data | filter http_data != null

//Extracting relevant info from http data
| alter http_data = to_json_string(arrayindex(http_data,0))
| alter http_req_user_agent_header = json_extract_scalar(http_data,"$.http_req_user_agent_header"), http_req_uri_path = json_extract_scalar(http_data,"$.http_req_uri_path"), http_req_host_header = json_extract_scalar(http_data,"$.http_req_host_header")

//List websites here
//Hacking
| filter (http_req_uri_path contains "adfind" or
          http_req_uri_path contains "procdump" or
          http_req_uri_path contains "psexec" or
          http_req_uri_path contains "bloodhound" or
          http_req_uri_path contains "lazagne" or
          http_req_uri_path contains "cobaltstrike" or
          http_req_uri_path contains "bruteratel" or
          http_req_uri_path contains "mimikatz" or
          http_req_uri_path contains "impacket" or
          http_req_uri_path contains "ngrok" or
          http_req_uri_path contains "gost" or
          http_req_uri_path contains "pdq" or
          http_req_uri_path contains "advanced-ip-scanner" or
          http_req_uri_path contains "angryip")
          //and
         //(http_req_uri_path not contains ".png")

//Lateral Movement
| filter (http_req_uri_path contains "ammyy" or
          http_req_uri_path contains "anydesk" or
          http_req_uri_path contains "screenconnect" or
          http_req_uri_path contains "teamviewer" or
          http_req_uri_path contains "realvnc" or
          http_req_uri_path contains "ultravnc" or
          http_req_uri_path contains "tightvnc" or
          http_req_uri_path contains "splashtop" or
          http_req_uri_path contains "bomgar" or
          http_req_uri_path contains "beyondtrust")

//Exfil
| filter (http_req_uri_path contains "rclone" or
          http_req_uri_path contains "pastebin" or
          http_req_uri_path contains "mega" or
          http_req_uri_path contains "box" or
          http_req_uri_path contains "pcloud" or
          http_req_uri_path contains "anonfiles" or
          http_req_uri_path contains "filezilla" or
          http_req_uri_path contains "udrop" or
          http_req_uri_path contains "winscp")

//Add your own IOCs here:
//| filter (http_req_uri_path contains "")

//Returning relevant fields
//Limiting to 1000 output results, sorted descending by time
| fields agent_hostname, http_req_uri_path, actor_process_image_name, actor_process_command_line, http_referer
| limit 1000
| sort desc _time

//Use this section to aggregate data for IR or CA analysis, turn off for CA reporting
//Filter for users, hostnames, IPs | Comp by hostnames that accessed each website
//| filter agent_hostname in ("Finding", "Finding")
//| filter actor_primary_username in ("Finding", "Finding")
//| filter action_remote_ip in ("Finding", "Finding")
//| comp count_distinct(agent_hostname) by http_req_uri_path


//Use this section to put finding in report format for CA, replace [Finding] with what you would like to report (wildcards* accepted), field for filtering can be changed
//| filter http_req_uri_path in ("Finding", "Finding")
//| comp count() as evCount, max(_time) as lastTime, min(_time) as firstTime, values(actor_process_image_path) as path, values(action_remote_ip) as action_remote_ip, values(action_local_port) as action_local_port, values(actor_process_command_line) as cmd by agent_hostname, actor_process_image_name 
//| alter discSource = "XDR - Network", xtra = ""
//| fields agent_hostname, action_local_port, actor_process_image_name , cmd, path, action_remote_ip, lastTime, xtra, discSource
```

## When to use

This query searches for hosts accessing certain sites. There are filters for some quick win hacking/lateral movement/exfil tools by default. Users can add specific IOCs as needed.

## Variations

_(No variations are documented for this entry.)_
