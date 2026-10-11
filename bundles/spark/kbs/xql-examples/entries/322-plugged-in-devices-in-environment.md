---
id: XQL-322-526016a8
title: Plugged-in Devices in Environment
category: investigation
dataset: device_control
tags:
  - preset
  - filter
  - fields
  - device_control
  - source:preset
---

# Plugged-in Devices in Environment

**Dataset**: `device_control`

```sql
preset = device_control
| filter event_sub_type = ENUM.DEVICE_PLUG
| filter agent_hostname in($host)
| fields agent_hostname, action_device_bus_type, action_device_usb_vendor_name, event_type, event_sub_type,*
```

## When to use

Details information about devices that have been physically connected to the environment’s endpoints, which enables monitoring unauthorized or risky device usage

## Variations

_(No variations are documented for this entry.)_
