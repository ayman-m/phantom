---
id: XQL-186-6672479f
title: Stitching a network story
category: investigation
dataset: network_story
tags:
  - preset
  - filter
  - fields
  - dedup
  - network_story
  - source:preset
  - stitching-demo
---

# Stitching a network story

**Dataset**: `network_story`

```sql
preset = network_story |  filter associated_products = "NGFW,XDR Agent,LabIDS" and actor_process_image_name != null | fields associated_products , * | dedup actor_process_image_name
```

## When to use

Stitching a network story. Queries the `network_story` preset, filtered on `associated_products = "NGFW,XDR Agent,LabIDS" and actor_process_image_name != null`. Uses stages: `preset`, `filter`, `fields`, `dedup`.

## Variations

_(No variations are documented for this entry.)_
