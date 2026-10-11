---
id: XQL-178-5ced7187
title: QR - Access to the PANW Sinkhole IP by Non Browser Process
category: detection
dataset: network_story
tags:
  - preset
  - filter
  - fields
  - comp
  - sort
  - alter
  - network_story
  - source:preset
  - edr
  - lowfi
  - panwopen
  - poc
  - dashboard
  - ca_network
---

# QR - Access to the PANW Sinkhole IP by Non Browser Process

**Dataset**: `network_story`

```sql
//Title: Access to the PANW Sinkhole IP by Non-Browser Process
//Description: Intended to be used as a way locate access to PANW sinkhole by non-browser proccess
//Dataset: network_story
//Tags: EDR,LowFi,PANWOpen,POC,Dashboard, ca_network

config timeframe = 30D

| preset = network_story // Using XDR network story preset
| filter action_remote_ip = "72.5.65.111" AND lowercase(actor_process_image_name) NOT IN
("chrome.exe", "msedge.exe","opera.exe", "firefox.exe", "iexplore.exe") // 72.5.65.111 is the default IP that is used to sinkhole IN the NGFW. The filter also looks to exclude browsers since many ads are being sinkholed

//Returning relevant fields
//| filter action_local_ip in ("[Finding]", "[Finding]") 
| fields agent_hostname, action_local_ip, action_remote_ip, action_remote_port, dst_action_external_hostname

//Use this section to aggregate data for CA analysis, turn off for reporting
//| filter actor_process_image_name in ("[Finding]", "[Finding]") 
//1st pass
//| comp count(_time ) as Total by agent_hostname , actor_process_image_name , actor_process_image_path
//| sort desc total


//Use this section to put finding in report format for CA, replace [Finding] with what you would like to report (wildcards* accepted), field for filtering can be changed
//| filter actor_process_image_name in ("[Finding]", "[Finding]") 
//| filter agent_hostname in ("[Finding]", "[Finding]")
//| alter disc_source = "Network Story"
//| fields agent_hostname, action_local_port, actor_process_image_name , actor_process_image_path, action_remote_ip, _time, disc_source
```

## When to use

Intended to be used as a way locate access to PANW sinkhole by non-browser proccess

## Variations

_(No variations are documented for this entry.)_
