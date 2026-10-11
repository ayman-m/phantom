---
id: XQL-283-c322b5ea
title: Webinar - Hunting Query
category: detection
dataset: xdr_data
tags:
  - config
  - filter
  - fields
  - xdr_data
  - source:dataset
---

# Webinar - Hunting Query

**Dataset**: `xdr_data`

```sql
config case_sensitive = false 
| dataset = xdr_data
|filter event_sub_type = PROCESS_START and lowercase(action_process_image_name) = "procdump*"
|filter lowercase(action_process_image_command_line ) contains "lsass" 
|fields agent_hostname, agent_version, actor_effective_username , action_process_image_name,action_process_image_command_line,actor_process_image_name, actor_process_image_command_line, action_process_image_path, action_process_image_sha256
```

## When to use

Webinar - Hunting Query. Queries the `xdr_data` dataset directly, filtered on `event_sub_type = PROCESS_START and lowercase(action_process_image_name) = "procdump*"`. Uses stages: `config`, `filter`, `fields`.

## Variations

_(No variations are documented for this entry.)_
