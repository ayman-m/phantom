---
id: XQL-230-468df36d
title: Unsigned Process creating dump file
category: investigation
dataset: xdr_file
tags:
  - preset
  - filter
  - fields
  - xdr_file
  - source:preset
---

# Unsigned Process creating dump file

**Dataset**: `xdr_file`

```sql
preset = xdr_file // Using the XDR file preset
| filter action_file_name ~= ".*?\.dmp|.*\.dump" and actor_process_signature_status != ENUM.SIGNED // Filtering for unsigned processes creating a dump file
| fields action_file_name as file_name , actor_process_image_name as process_name, actor_process_command_line as process_cmd, actor_process_image_sha256 as process_sha256 // Selecting the relevant fields
```

## When to use

Displays all dump files created by processes that are not validly signed

## Variations

_(No variations are documented for this entry.)_
