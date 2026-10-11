---
id: XQL-732-160ffc92
title: Recent incidents by severity + status (7d)
category: investigation
dataset: incidents
tags:
  - filter
  - comp
  - sort
  - limit
  - incidents
---

# Recent incidents by severity + status (7d)

**Dataset**: `incidents`

```sql
config timeframe = 7d
| dataset = incidents
| comp count() as cnt by severity, status
| sort desc cnt
| limit 10
```

## When to use

Incident triage matrix — severity × status. New + critical = highest priority; resolved + low = ready to archive.

## Variations

_(No variations are documented for this entry.)_
