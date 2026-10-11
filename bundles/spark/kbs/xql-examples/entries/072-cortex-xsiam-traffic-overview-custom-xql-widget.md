---
id: XQL-072-1800f63a
title: Cortex XSIAM Traffic Overview - Custom XQL Widget
category: investigation
tags:
  - alter
  - comp
  - sort
  - view
---

# Cortex XSIAM Traffic Overview - Custom XQL Widget

**Dataset**: `(none)`

```sql
preset = network_story
| alter proto = to_string(action_network_protocol )
| alter proto = if(proto = "1", "ICMP",proto = "6", "TCP",proto = "17", "UDP", proto = "47", "GRE", proto = "4", "IP-in-IP")
| comp count(event_id ) as traffic_count by proto
| sort desc traffic_count
| view graph type = pie subtype = semi_donut xaxis = proto yaxis = traffic_count
```

## When to use

Cortex XSIAM Traffic Overview - Custom XQL Widget. Queries the `(none)` preset. Uses stages: `alter`, `comp`, `sort`, `view`.

## Variations

_(No variations are documented for this entry.)_
