---
id: XQL-719-36e10225
title: Endpoints grouped by OS family
category: investigation
dataset: endpoints
tags:
  - comp
  - sort
  - limit
  - endpoints
---

# Endpoints grouped by OS family

**Dataset**: `endpoints`

```sql
dataset = endpoints
| comp count() as cnt, count_distinct(endpoint_id) as unique_endpoints by platform, operating_system
| sort desc cnt
| limit 10
```

## When to use

OS distribution baseline — useful for capacity planning + identifying outliers (e.g. an old Windows 7 box in a Windows-11-only fleet).

## Variations

_(No variations are documented for this entry.)_
