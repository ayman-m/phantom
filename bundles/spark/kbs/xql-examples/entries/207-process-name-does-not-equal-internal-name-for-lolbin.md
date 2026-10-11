---
id: XQL-207-5599fbe5
title: Process name does not equal internal name for LOLBin
category: investigation
dataset: xdr_data
tags:
  - filter
  - alter
  - fields
  - dedup
  - xdr_data
  - source:dataset
---

# Process name does not equal internal name for LOLBin

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type= ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START and action_process_file_info != null // Looking at process start events where we have the process original info
 | alter original_name=json_extract_scalar(lowercase(action_process_file_info), "$.original_name") // This function gets the original name of the process
 | alter remove_exe_process = if(lowercase(action_process_image_name) contains ".exe", replace(lowercase(action_process_image_name),".exe",""),lowercase(action_process_image_name)) // Removing .exe from the process name since in some cases the original name does not contain .exe. The next few lines normalize the data for the original name as well based on some cases seen in the data 
 | alter remove_exe_internal = if(original_name contains ".exe", replace(original_name,".exe",""),original_name) // See comment above
 | alter remove_exe_internal = if(remove_exe_internal contains "_exe", replace(remove_exe_internal,"_exe",""),remove_exe_internal) // See comment above
 | filter lowercase(remove_exe_internal) != lowercase(remove_exe_process) and lowercase(remove_exe_internal) in ("powershell", "wscript", "cscript", "mshta", "bitsadmin", "certutil", "ftp", "gscript", "hh", "reg", "regsvr32", "wmic", "rundll32", "netsh", "cmd", "arp", "route", "netstat", "net", "systeminfo", "wevtutil", "whoami", "ipconfig", "tasklist", "sc", "schtasks") // Filtering for cases where the normalized original name DOES NOT equal normalized process name AND the the normalized original name is associated with a lolbin
 | fields action_process_image_name as Process_Name, original_name as Full_Original_Name, action_process_image_path as Process_Path, remove_exe_internal as Clean_original_Name, remove_exe_process as Clean_Process_Name // Selecting only the relevant fields to show
 | dedup Process_Name, Full_Original_Name, Process_Path, Clean_original_Name, Clean_Process_Name by asc _time // Showing each tuple only once
```

## When to use

Search for cases where lolbins have been renamed and executed to hide what they actually are, by extracting the internal name of a process and comparing it with the actual process name

## Variations

_(No variations are documented for this entry.)_
