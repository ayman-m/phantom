---
id: XQL-013-8d033bf1
title: Captive Portal Continue Click
category: investigation
dataset: panw_ngfw_url_raw
tags:
  - fields
  - filter
---

# Captive Portal Continue Click

**Dataset**: `panw_ngfw_url_raw`

```sql
dataset = panw_ngfw_url_raw
| filter action = "continue"
| fields source_user, action
```

## When to use

Captive Portal Continue Click. Queries the `panw_ngfw_url_raw` dataset directly, filtered on `action = "continue"`. Uses stages: `filter`, `fields`.

## Variations

_(No variations are documented for this entry.)_
