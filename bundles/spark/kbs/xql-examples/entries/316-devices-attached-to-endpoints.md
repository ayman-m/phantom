---
id: XQL-316-827161a2
title: Devices Attached to Endpoints
category: investigation
dataset: device_control
tags:
  - preset
  - filter
  - comp
  - sort
  - device_control
  - source:preset
---

# Devices Attached to Endpoints

**Dataset**: `device_control`

```sql
preset = device_control
| filter agent_hostname in($host)
| comp values(agent_hostname) as agent_list, count_distinct(agent_hostname) as  unique_agents by action_device_usb_serial_number
| sort desc unique_agents
```

## When to use

Lists the devices that have been connected to endpoints to provide visibility into potential unauthorized hardware or new devices that can pose security risks

## Variations

_(No variations are documented for this entry.)_
