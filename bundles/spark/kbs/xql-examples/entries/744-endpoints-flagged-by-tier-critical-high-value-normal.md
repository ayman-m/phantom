---
id: XQL-744-578b9aaf
title: Endpoints flagged by tier — critical / high-value / normal
category: investigation
dataset: endpoints
tags:
  - alter
  - comp
  - sort
  - limit
  - endpoints
  - conditional
---

# Endpoints flagged by tier — critical / high-value / normal

**Dataset**: `endpoints`

```sql
dataset = endpoints
| alter tier = if(operating_system contains "Server", "critical", if(cloud_provider != null, "high-value", "normal"))
| comp count() as cnt by tier, operating_system
| sort desc cnt
| limit 10
```

## When to use

Heuristic endpoint tiering — server OSes are 'critical', cloud-hosted are 'high-value', rest are 'normal'. Demonstrates conditional categorization on `endpoints` data.

## Variations

_(No variations are documented for this entry.)_
