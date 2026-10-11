---
id: XQL-197-8df483bc
title: LOLBINS uploading more than 10MB
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

# LOLBINS uploading more than 10MB

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.NETWORK and lowercase(actor_process_image_name) in ("powershell.exe","wscript.exe", "cscript.exe", "mshta.exe", "bitsadmin.exe", "certutil.exe", "ftp.exe", "gscript.exe", "wmic.exe", "rundll32.exe") // Filtering by network and by acting process in a list contains common LOLBins who are used to upload data. Note both filters apply lower case logic to the fields
 | fields actor_process_image_path as Process_Path, actor_process_command_line as Process_CMD, action_upload as Upload // Selecting the fields
 | comp sum(Upload) as uploaded_bytes by Process_Path, Process_CMD // Summing all data uploaded by a pair of process and command line
 | filter uploaded_bytes > 10485760 // Filteting by uploaded size is larger than 10MB
 | sort desc uploaded_bytes // Sorting in decending order by size
```

## When to use

Display the path and cmd of LOLBINs Uploading more than 10MB

## Variations

_(No variations are documented for this entry.)_
