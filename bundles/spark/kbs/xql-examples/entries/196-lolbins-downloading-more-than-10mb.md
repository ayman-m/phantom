---
id: XQL-196-2897a278
title: LOLBINS downloading more than 10MB
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

# LOLBINS downloading more than 10MB

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.NETWORK and lowercase(actor_process_image_name) in ("powershell.exe","wscript.exe", "cscript.exe", "mshta.exe", "bitsadmin.exe", "certutil.exe", "ftp.exe", "gscript.exe", "wmic.exe", "rundll32.exe") // Filtering by network and by acting process in a list contains common LOLBins who are used to download data. Note the lower case logic applied to the field
 | fields actor_process_image_path as Process_Path, actor_process_command_line as Process_CMD, action_download as Download // Selecting the fields
 | comp sum(Download) as downloaded_bytes by Process_Path, Process_CMD // Summing all data downloaded by a pair of process and command line
 | filter downloaded_bytes > 10485760 // Filteting by download size is larger than 10MB
 | sort desc downloaded_bytes // Sorting in descending order by size
```

## When to use

Display the path and cmd of LOLBINs downloading more than 10MB

## Variations

_(No variations are documented for this entry.)_
