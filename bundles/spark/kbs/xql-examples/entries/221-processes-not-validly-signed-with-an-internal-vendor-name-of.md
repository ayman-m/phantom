---
id: XQL-221-730306a8
title: Processes not validly signed with an internal vendor name of a known vendor
category: investigation
dataset: xdr_data
tags:
  - filter
  - alter
  - fields
  - xdr_data
  - source:dataset
---

# Processes not validly signed with an internal vendor name of a known vendor

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the agent dataset
 | filter event_sub_type = ENUM.PROCESS_START and action_process_file_info != null and action_process_signature_status != ENUM.SIGNED // Looking at process start events for processes that have the file info and are not validly signed
 | alter internal_company_name = json_extract_scalar(action_process_file_info, "$.company"), signature_status_string = to_string(action_process_signature_status) // Getting the company name from the info, and making the signature state a string as some function later require a string
 | filter lowercase(internal_company_name) ~= ".*microsoft.*|.*adobe.*|.*vmware.*|.*apache.*|.*google.*|.*mozilla.*|.*zoom.*|.*oracle.*" // Filtering for cases where the internal company name is like a known trusted vendor
 | alter signature_status = if(signature_status_string = "3", "Unsigned", signature_status_string = "2", "Signed Invalid", signature_status_string = "4", "Failed To Obtain", signature_status_string = "5", "Weak Hash", signature_status_string = "6", "Unsupported", signature_status_string = "7", "Invalid CVE 2020_0601", signature_status_string) // The signature_status_string field can return an enum, so this if function, which also doubles as 'case' function, parses the values to readable form
 | fields internal_company_name, signature_status , action_process_image_path, action_process_image_sha256 // Getting the relevant fields
```

## When to use

Evaluate the vendor name in the process information to display processes claiming to belong to a known vendor that are are not validly signed.

## Variations

_(No variations are documented for this entry.)_
