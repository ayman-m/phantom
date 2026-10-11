---
id: XQL-280-cc57cf4d
title: Network Story Query
category: investigation
dataset: network_story
tags:
  - preset
  - fields
  - network_story
  - source:preset
---

# Network Story Query

**Dataset**: `network_story`

```sql
preset = network_story |
fields _time, _vendor, _product, story_publish_timestamp, action_app_id_transitions, action_session_duration, dst_action_country, user_id, dst_user_id, action_network_protocol, action_network_success, dst_action_external_hostname, dns_query_name, dns_query_type, dns_resolutions, dns_reply_code, association_strength, dst_association_strength, action_remote_port, action_total_download, action_remote_ip, action_external_hostname, action_total_upload, action_country, action_local_port, action_local_ip, action_network_is_npcap, actor_process_image_path, actor_process_command_line, actor_process_signature_vendor, actor_process_image_md5, actor_process_image_sha256, actor_process_image_name, actor_process_signature_status, actor_effective_username, actor_process_instance_id, actor_process_os_pid, actor_thread_thread_id, actor_type, actor_remote_ip, actor_remote_host, actor_remote_port, actor_remote_pipe_name, agent_ip_addresses, agent_hostname, agent_os_type, agent_install_type, causality_actor_process_signature_status, causality_actor_process_image_sha256, causality_actor_process_image_path, causality_actor_process_image_md5, causality_actor_process_command_line, causality_actor_process_os_pid, causality_actor_process_signature_vendor, causality_actor_process_image_name, causality_actor_type, causality_actor_remote_ip, causality_actor_remote_host, causality_actor_remote_port, causality_actor_remote_pipe_name, event_id, event_type, event_sub_type, insert_timestamp, os_actor_process_image_path, os_actor_process_command_line, os_actor_process_image_name, os_actor_process_signature_status, os_actor_process_os_pid, os_actor_thread_thread_id, dst_agent_ip_addresses, dst_agent_hostname, dst_agent_os_type, dst_agent_install_type, dst_actor_process_image_path, dst_actor_process_command_line, dst_actor_process_signature_vendor, dst_actor_process_image_md5, dst_actor_process_image_sha256, dst_actor_process_image_name, dst_actor_process_signature_status, dst_actor_effective_username, dst_actor_process_os_pid, dst_actor_thread_thread_id, dst_causality_actor_process_signature_status, dst_causality_actor_process_image_sha256, dst_causality_actor_process_image_path, dst_causality_actor_process_image_md5, dst_causality_actor_process_command_line, dst_causality_actor_process_os_pid, dst_causality_actor_process_signature_vendor, dst_causality_actor_process_image_name, dst_os_actor_process_image_path, dst_os_actor_process_command_line, dst_os_actor_process_image_name, dst_os_actor_process_signature_status, dst_os_actor_process_os_pid, dst_os_actor_thread_thread_id, associated_vendors, associated_products, dst_agent_mac_addresses, associated_serials, associated_device_names, associated_versions, associated_rules, agent_mac_addresses
```

## When to use

Network Story Query. Queries the `network_story` preset. Uses stages: `preset`, `fields`.

## Variations

_(No variations are documented for this entry.)_
