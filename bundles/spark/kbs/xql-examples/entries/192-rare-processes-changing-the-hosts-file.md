---
id: XQL-192-bbc1e3a6
title: Rare Processes changing the hosts file
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

# Rare Processes changing the hosts file

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.FILE and event_sub_type = ENUM.FILE_WRITE and lowercase(action_file_path) in ("/etc/hosts", "c:\windows\system32\drivers\etc\hosts") // Filtering by event type of file write and the file is either the linux path or the windows path. Note the lower case logic applied to the field
 | fields actor_process_image_path as Process_Path, actor_process_command_line as Command_Line, action_file_path as File_Path,event_id // Selecting the process path and command line, as well as the file being changed
 | comp count(event_id) as Counter by Process_Path, Command_Line, File_Path // Counting how many times each process changed the hosts file
 | filter Counter < 10 // Filtering for processes doing this change less than 10 times
 | sort desc Counter // Sorting by occurrences in a descending order
```

## When to use

Display a process that changed the hosts file fewer than 10 times

## Variations

_(No variations are documented for this entry.)_
