---
id: XQL-729-2bb157b7
title: Issues by category (7d)
category: investigation
dataset: issues
tags:
  - filter
  - comp
  - sort
  - limit
  - issues
  - xdm
---

# Issues by category (7d)

**Dataset**: `issues`

```sql
config timeframe = 7d
| dataset = issues
| comp count() as cnt by xdm.issue.category
| sort desc cnt
| limit 10
```

## When to use

Issue category distribution via the XDM schema. Maps to the MITRE-tagged categories XSIAM assigns automatically.

## Variations

_(No variations are documented for this entry.)_
