---
id: XQL-201-4962ca8b
title: Processes running multiple recon commands
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

# Processes running multiple recon commands

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.PROCESS and event_sub_type = ENUM.PROCESS_START and lowercase(action_process_image_name) in ("arp.exe", "route.exe", "netstat.exe", "net.exe", "systeminfo.exe", "wevtutil.exe", "whoami.exe", "ipconfig.exe", "netsh.exe", "tasklist.exe", "sc.exe", "wmic.exe", "schtasks.exe", "reg.exe") // Filtering for process execution and acting process name is in a list of processes commonly used for recon. Note lower case logic that's applied to the field
 | fields actor_process_command_line, actor_process_image_path, actor_process_os_pid, action_process_image_command_line // Getting the relevant fields
 | comp count_distinct(action_process_image_command_line) as Counter by actor_process_os_pid, actor_process_command_line, actor_process_image_path // Counting distinct command lines per actor process
 | filter Counter >= 5 // Filtering for 5 or more unique command line args by one process
 | sort desc Counter // Sorting in descending order by number of unique command line args
```

## When to use

Display a single process that's spawning multiple processes often used for recon such as arp, whoami, systeminfo and more

## Variations

_(No variations are documented for this entry.)_
