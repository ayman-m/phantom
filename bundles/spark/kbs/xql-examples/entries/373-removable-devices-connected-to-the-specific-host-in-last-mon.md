---
id: XQL-373-31dcd1e8
title: Removable Devices Connected to the Specific Host in Last Month
category: investigation
dataset: xdr_data
tags:
  - config
  - filter
  - alter
  - fields
  - xdr_data
  - source:dataset
---

# Removable Devices Connected to the Specific Host in Last Month

**Dataset**: `xdr_data`

```sql
config timeframe = 30d case_sensitive = false | dataset = xdr_data | filter event_type = ENUM.MOUNT and event_sub_type = ENUM.MOUNT_DRIVE_MOUNT and agent_hostname = $host
| alter Drive_Type = json_extract(to_json_string(action_mount_device_info),"$.storage_device_drive_type"), Filesystem = json_extract_scalar(to_json_string(action_mount_device_info),"$.storage_device_filesystem"), Drive_Letter = json_extract_scalar(to_json_string(action_mount_device_info),"$.storage_device_mount_point"), Device_Serial_Number = json_extract_scalar(to_json_string(action_mount_device_info),"$.storage_device_serial_number")
| filter Drive_Type = "2" //2 is a removable device
| fields agent_hostname, Drive_Letter, Drive_Type, Filesystem, Device_Serial_Number, action_device_usb_vendor_name, action_device_usb_product_name
```

## When to use

Lists any removable devices connected to a specific host in the last month

## Variations

_(No variations are documented for this entry.)_
