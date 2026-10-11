---
id: XQL-815-4c622960
title: Hosts with OS caption (detailed OS string)
category: investigation
dataset: host_inventory
tags:
  - filter
  - fields
  - sort
  - limit
  - host_inventory
---

# Hosts with OS caption (detailed OS string)

**Dataset**: `host_inventory`

```sql
dataset = host_inventory
| filter os_caption != null
| fields host_name, os_type, os_caption, agent_name, agent_domain
| sort asc os_caption
| limit 10
```

## When to use

Per-host OS detail using `os_caption` (the long-form OS name, e.g. 'Windows Server 2022'). Sorted alphabetically by OS string.

## Variations

_(No variations are documented for this entry.)_
