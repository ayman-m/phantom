---
id: XQL-389-92cb9212
title: Query File Activities Related to Specific Hash in Last Month
category: investigation
dataset: xdr_data
tags:
  - config
  - filter
  - fields
  - join
  - alter
  - xdr_data
  - source:dataset
---

# Query File Activities Related to Specific Hash in Last Month

**Dataset**: `xdr_data`

```sql
config case_sensitive = false timeframe = 30d | dataset = xdr_data
| filter event_type = ENUM.FILE and (event_sub_type = ENUM.FILE_WRITE or event_sub_type = ENUM.FILE_RENAME or event_sub_type = ENUM.FILE_CREATE_NEW or event_sub_type = ENUM.FILE_REMOVE )
| filter action_file_sha256 = $hash or action_file_md5 = $hash
| fields agent_hostname,agent_ip_addresses, actor_effective_username, actor_process_image_name ,event_sub_type ,action_file_path
| join conflict_strategy = left type = left (config case_sensitive = false timeframe = 1Y | dataset = xdr_data
| filter event_type = ENUM.FILE and event_sub_type = ENUM.FILE_REMOVE
| filter action_file_sha256 = $hash or action_file_md5 = $hash |alter deleted = "yes" | fields agent_hostname , action_file_path , deleted ) as delete_check delete_check.agent_hostname = agent_hostname and delete_check.action_file_path = action_file_path
| alter deleted = if(deleted = null, "no" , deleted)
| fields agent_hostname,agent_ip_addresses, actor_effective_username, actor_process_image_name ,event_sub_type ,action_file_path, deleted
```

## When to use

List the file actions that are related to a specific hash in last month (Create/Write/Rename)

## Variations

_(No variations are documented for this entry.)_
