---
id: XQL-390-62fda99f
title: Process Executions of Specific Hash in Last Month
category: investigation
dataset: xdr_data
tags:
  - config
  - filter
  - fields
  - view
  - xdr_data
  - source:dataset
---

# Process Executions of Specific Hash in Last Month

**Dataset**: `xdr_data`

```sql
config timeframe = 30d | dataset = xdr_data
| filter action_process_image_sha256 = $hash or action_process_image_md5 = $hash or action_file_sha256 = $hash or action_module_sha256 = $hash
| fields _time, agent_hostname,event_type, event_sub_type, actor_effective_username , action_process_image_path, action_process_image_sha256, action_process_image_md5, actor_process_image_name , action_file_path
| view column order = populated
```

## When to use

Searches for the given hash, and lists all the events in the last month where this hash was executed and observed by the XDR agent. This can help identify the endpoints which have executed a suspicous file/malware

## Variations

_(No variations are documented for this entry.)_
