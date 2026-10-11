---
id: XQL-790-dec89110
title: Endpoints by content-version (rollout-progress view)
category: investigation
dataset: endpoints
tags:
  - filter
  - comp
  - sort
  - limit
  - endpoints
---

# Endpoints by content-version (rollout-progress view)

**Dataset**: `endpoints`

```sql
dataset = endpoints
| filter content_version != null
| comp count() as cnt by content_version
| sort desc cnt
| limit 10
```

## When to use

Content-version distribution across endpoints. Reveals signature/content rollout progress + identifies endpoints lagging the latest content.

## Variations

_(No variations are documented for this entry.)_
