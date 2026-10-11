---
id: XQL-213-fce918cb
title: Top 10 users creating files on a removable device
category: investigation
dataset: xdr_data
tags:
  - filter
  - alter
  - fields
  - comp
  - sort
  - limit
  - view
  - xdr_data
  - source:dataset
---

# Top 10 users creating files on a removable device

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.FILE and event_sub_type = ENUM.FILE_CREATE_NEW // Looking for file creation events
 | alter Drive_Type = json_extract(to_json_string(action_file_device_info),"$.storage_device_drive_type") // Getting details about the device a file was created on
 | filter drive_type = "2" // Filtering by drive type 2 which is 'Removable Media'
 | fields action_file_path as File_Path, actor_effective_username as Username // Selecting the relevant fields
 | comp count_distinct(File_Path) as Count_Of_Unique_Files by Username // Counting the amount of distinct files by path created on the removable device
 | sort desc Count_Of_Unique_Files // Sorting in descending order by number of distinct files
 | limit 10 // Show only the top 10 users
 | view graph type = pie show_callouts = true xaxis = username yaxis = Count_Of_Unique_Files // Showing a pie chart of the results
```

## When to use

Display the top 10 users who created files on a removable device such as a USB storage device

## Variations

_(No variations are documented for this entry.)_
