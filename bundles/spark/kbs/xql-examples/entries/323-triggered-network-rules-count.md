---
id: XQL-323-26d1ef76
title: Triggered Network Rules Count
category: investigation
dataset: network_story
tags:
  - preset
  - filter
  - comp
  - network_story
  - source:preset
---

# Triggered Network Rules Count

**Dataset**: `network_story`

```sql
preset = network_story
| filter associated_rules != null and associated_rules != ""
| comp count() by associated_rules
```

## When to use

Counts the number of network security rules triggered across the environment to help track network activity and identify potential misconfigurations or security events

## Variations

_(No variations are documented for this entry.)_
