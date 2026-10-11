---
id: XQL-187-0730de8e
title: Stitching Identity Data
category: investigation
dataset: authentication_story
tags:
  - preset
  - fields
  - filter
  - authentication_story
  - source:preset
  - stitching-identity
---

# Stitching Identity Data

**Dataset**: `authentication_story`

```sql
preset = authentication_story | fields associated_products , auth_service , auth_identity , auth_outcome , auth_client , action_local_ip , action_local_port , auth_target , action_remote_ip , action_remote_port , auth_domain , association_strength , dst_association_strength , actor_process_instance_id , os_actor_process_image_name   | filter associated_products = "NGFW,XDR Agent" | filter auth_identity not contains "$" and auth_identity != null
```

## When to use

Stitching Identity Data. Queries the `authentication_story` preset, filtered on `associated_products = "NGFW,XDR Agent"`. Uses stages: `preset`, `fields`, `filter`.

## Variations

_(No variations are documented for this entry.)_
