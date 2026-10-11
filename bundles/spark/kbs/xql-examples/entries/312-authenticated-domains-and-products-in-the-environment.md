---
id: XQL-312-9915243c
title: Authenticated Domains and Products in the Environment
category: investigation
dataset: authentication_story
tags:
  - preset
  - alter
  - comp
  - sort
  - limit
  - authentication_story
  - source:preset
---

# Authenticated Domains and Products in the Environment

**Dataset**: `authentication_story`

```sql
preset = authentication_story
| alter target_or_domain = coalesce(auth_target , auth_domain)
| comp count_distinct(auth_client) as unique_clients by associated_products, target_or_domain
| sort desc unique_clients
| limit 100
```

## When to use

Lists the domains and products authenticated in the environment and offering insights into the systems and applications interacting with the infrastructure and their associated trust relationships

## Variations

_(No variations are documented for this entry.)_
