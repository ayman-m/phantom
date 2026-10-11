---
id: XQL-226-7e618522
title: Users running Sudo Su command
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - xdr_data
  - source:dataset
---

# Users running Sudo Su command

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset 
| filter action_process_image_command_line ~= "\s+su\b" and action_process_image_name = "sudo" // Filtering for executions of sudo command with su in the command line
| fields actor_effective_username as source_username, action_process_username as target_username, action_process_image_command_line as command_line // Showing the users
```

## When to use

Display cases where users switch to another user on non-windows OSs

## Variations

_(No variations are documented for this entry.)_
