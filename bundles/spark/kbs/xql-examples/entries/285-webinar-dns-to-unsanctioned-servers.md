---
id: XQL-285-4c57d5ed
title: Webinar - DNS to Unsanctioned Servers
category: investigation
dataset: network_story
tags:
  - preset
  - fields
  - filter
  - network_story
  - source:preset
---

# Webinar - DNS to Unsanctioned Servers

**Dataset**: `network_story`

```sql
preset = network_story 
| fields action_network_protocol , action_app_id_transitions , action_local_ip , action_remote_ip , action_remote_port , dns_query_type , dns_query_name , dns_resolutions , actor_process_command_line, associated_products 
| filter action_remote_port = 53 and action_local_ip not in(dataset = sanctioned_dns_servers | fields server) and action_remote_ip not in(dataset = sanctioned_dns_servers | fields server)
```

## When to use

Webinar - DNS to Unsanctioned Servers. Queries the `network_story` preset, filtered on `action_remote_port = 53 and action_local_ip not in(dataset = sanctioned_dns_servers`. Uses stages: `preset`, `fields`, `filter`.

## Variations

_(No variations are documented for this entry.)_
