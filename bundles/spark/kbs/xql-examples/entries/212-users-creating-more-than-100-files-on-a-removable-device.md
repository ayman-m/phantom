---
id: XQL-212-f2b862ea
title: Users creating more than 100 files on a removable device
category: investigation
dataset: xdr_data
tags:
  - filter
  - alter
  - fields
  - comp
  - sort
  - xdr_data
  - source:dataset
---

# Users creating more than 100 files on a removable device

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.FILE and event_sub_type = ENUM.FILE_CREATE_NEW // Looking for file creation events
 | alter Drive_Type = json_extract(to_json_string(action_file_device_info),"$.storage_device_drive_type"), Filesystem = json_extract_scalar(to_json_string(action_file_device_info),"$.storage_device_filesystem"), Drive_Letter = json_extract_scalar(to_json_string(action_file_device_info),"$.storage_device_mount_point"), Device_Serial_Number = json_extract_scalar(to_json_string(action_file_device_info),"$.storage_device_serial_number") // Getting details about the device a file was created on
 | filter drive_type = "2" // Filtering by drive type 2 which is 'Removable Media'
 | fields action_file_path as File_Path, actor_effective_username as Username, Filesystem, Drive_Letter, Device_Serial_Number // Selecting the relevant fields
 | comp count_distinct(File_Path) as Count_Of_Unique_Files by Username, Filesystem, Drive_Letter, Device_Serial_Number // Counting the amount of distinct files by path created on the removable device
 | filter Count_Of_Unique_Files > 100 // Filtering for more than 100 files
 | sort desc Count_Of_Unique_Files // Sorting in descending order by number of distinct files
```

## When to use

Display users who created more than 100 files on a removable device such as a USB storage device, alongside the driver letter, filesystem and serial

## Variations

_(No variations are documented for this entry.)_
