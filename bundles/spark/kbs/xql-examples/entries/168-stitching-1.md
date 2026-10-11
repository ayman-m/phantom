---
id: XQL-168-6bfd9ff4
title: Stitching 1
category: investigation
dataset: network_story
tags:
  - preset
  - fields
  - filter
  - network_story
  - source:preset
---

# Stitching 1

**Dataset**: `network_story`

```sql
preset = network_story 
| fields _product , _time , _vendor , event_id , action_app_id_transitions , action_country , action_local_ip , action_local_port , action_network_is_npcap , action_network_protocol , action_network_success , action_remote_ip , action_remote_port , action_session_duration , action_total_download , action_total_upload , actor_type  , associated_device_names , associated_products , associated_rules , dst_action_country , dst_actor_effective_username , dst_actor_process_command_line , dst_actor_process_image_name ,dst_actor_process_image_path , dst_agent_hostname , dst_agent_ip_addresses , dst_causality_actor_process_command_line, dst_causality_actor_process_image_name , dst_os_actor_process_image_name , event_type , event_sub_type , story_publish_timestamp
| filter event_id = "MjQ2NTE0MDkzNjg0MTc4MjU1OQ=="
```

## When to use

Stitching 1. Queries the `network_story` preset, filtered on `event_id = "MjQ2NTE0MDkzNjg0MTc4MjU1OQ=="`. Uses stages: `preset`, `fields`, `filter`.

## Variations

_(No variations are documented for this entry.)_
