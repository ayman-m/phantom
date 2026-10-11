---
id: XQL-180-18fedbfc
title: QR - Procdump interacting with LSASS
category: detection
dataset: xdr_data
tags:
  - filter
  - fields
  - comp
  - alter
  - xdr_data
  - source:dataset
  - hunt-demo
  - edr
  - windows
  - highfi
  - irko
  - panwopen
  - poc
  - ca_execution
---

# QR - Procdump interacting with LSASS

**Dataset**: `xdr_data`

```sql
//Title: Procdump interacting with LSASS
//Tags: EDR,Windows,HighFi,IRKO,PANWOpen,POC,CA_execution
//Description: Query looks for instances of Procdump interacting with lsass.exe
//Dataset: xdr_data
//Requirements: EDR data must be enabled.  This is not a forensics search, will only return results from after the Cortex XDR agent was installed  
//Filters:  Filtering for procdump execution with command lines that contain lsass

// Set query to NOT case_sensitive
config case_sensitive = false 

// Use the xdr_data data set (EDR data)
| dataset = xdr_data

// Filtering for process start events that contain procdump and command line that contains lsass
|filter event_sub_type = PROCESS_START and lowercase(action_process_image_name) = "procdump*" // looking for Procdump or Procdump64
|filter lowercase(action_process_image_command_line ) contains "lsass" // looking for procdump attempting to touch lsass

//Return relevant fields 
|fields agent_hostname, agent_version, actor_effective_username , action_process_image_name,action_process_image_command_line,actor_process_image_name, actor_process_image_command_line, action_process_image_path, action_process_image_sha256

/*
// XDR Process - report in execution tab for Comp Assmt
| comp count() as runCount, max(_time) as lastTime by agent_hostname, action_process_image_command_line, actor_effective_username , action_process_image_name, action_process_image_path, action_process_image_sha256
| alter sha1 = "", discSource = "XDR - Processes", xtra = ""
| fields agent_hostname, action_process_image_command_line, actor_effective_username , action_process_image_name, action_process_image_path, sha1, action_process_image_sha256, runCount, lastTime, xtra, discSource


*/
```

## When to use

Query looks for instances of Procdump interacting with lsass.exe Filter rationale: Filtering for procdump execution with command lines that contain lsass

## Variations

_(No variations are documented for this entry.)_
