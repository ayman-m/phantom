---
id: XQL-189-777ecb07
title: Rare Combinations of CGO, LOLBin Process and Child Process
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - comp
  - sort
  - xdr_data
  - source:dataset
---

# Rare Combinations of CGO, LOLBin Process and Child Process

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START and lowercase(actor_process_image_name) in ("powershell.exe", "wscript.exe", "cscript.exe", "mshta.exe", "bitsadmin.exe", "certutil.exe", "ftp.exe", "gscript.exe", "hh.exe", "reg.exe", "regsvr32.exe", "wmic.exe", "rundll32.exe", "netsh.exe") and lowercase(action_process_image_path) != "c:\windows\system32\conhost.exe"// Filtering by process execution, and by acting process (who spawns a child process) in a list contains common LOLBins, and child process is not conhost.exe. Note both filters apply lower case logic to the fields
 | fields causality_actor_process_image_path as CGO_Process_Path, causality_actor_process_command_line as CGO_Process_Command_Line,actor_process_image_path as Parent_Process_Path, actor_process_command_line as Parent_Process_Command_Line, action_process_image_path as Child_Process_Path, action_process_image_command_line as Child_Process_Command_Line, event_id // Selecting the CGO and its command line, the acting process and its command line and the child process and its command lines
 | comp count(event_id) as Counter by CGO_Process_Path, CGO_Process_Command_Line, Parent_Process_Path, Parent_Process_Command_Line, Child_Process_Path, Child_Process_Command_Line // Counting occurrences 
 | filter Counter < 10 // Filtering for CGO/Process/Child seen less than 10 times
 | sort desc counter // Sorting by occurrences in a descending order
```

## When to use

Display CGO + LOLBINS processes + child processes seen fewer than 10 times in a given timeframe

## Variations

_(No variations are documented for this entry.)_
