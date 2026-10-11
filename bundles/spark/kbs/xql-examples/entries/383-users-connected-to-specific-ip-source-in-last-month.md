---
id: XQL-383-09f3d7d3
title: Users Connected to Specific IP/Source in Last Month
category: investigation
dataset: network_story
tags:
  - config
  - preset
  - filter
  - dedup
  - fields
  - network_story
  - source:preset
---

# Users Connected to Specific IP/Source in Last Month

**Dataset**: `network_story`

```sql
config timeframe = 30d | preset = network_story
| filter action_remote_ip = $ip
| dedup actor_effective_username
| fields actor_effective_username ,action_local_ip , action_remote_ip , action_remote_port , action_app_id_transitions
```

## When to use

Lists all the events with a specific IP address in the last month, and includes the applicable user fields

## Variations

_(No variations are documented for this entry.)_
