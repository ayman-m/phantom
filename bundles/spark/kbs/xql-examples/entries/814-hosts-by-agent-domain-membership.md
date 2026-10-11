---
id: XQL-814-e95a47e9
title: Hosts by agent-domain membership
category: investigation
dataset: host_inventory
tags:
  - filter
  - comp
  - sort
  - limit
  - host_inventory
---

# Hosts by agent-domain membership

**Dataset**: `host_inventory`

```sql
dataset = host_inventory
| filter agent_domain != null
| comp count() as cnt by agent_domain
| sort desc cnt
| limit 10
```

## When to use

AD domain membership distribution. Field is `agent_domain` in this tenant.

## Variations

_(No variations are documented for this entry.)_
