---
id: XQL-224-6e315488
title: Large FTP sessions
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - comp
  - xdr_data
  - source:dataset
---

# Large FTP sessions

**Dataset**: `xdr_data`

```sql
// NOTE: this query requires Palo Alto Networks NGFW data
 dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.STORY and action_app_id_transitions contains "ftp" // Looking for FTP connections by app-id
 | fields action_local_ip as source_ip, action_remote_ip as destination_ip, action_total_upload , action_total_download // Getting the source and destination IPs, upload and download
 | comp sum(action_total_upload) as upload, sum(action_total_download) as download by source_ip , destination_ip // Summing up the upload and download between the two IPs
 | filter upload > 104857600 or download > 104857600 // Looking for cases where the upload OR the download are more than 100MB
```

## When to use

Display cases where connections between two IP addresses over FTP resulted in either 100MB download or 100MB upload of data

## Variations

_(No variations are documented for this entry.)_
