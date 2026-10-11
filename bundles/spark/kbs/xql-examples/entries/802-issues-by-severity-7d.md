---
id: XQL-802-0164bfcc
title: Issues by severity (7d)
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

# Issues by severity (7d)

**Dataset**: `issues`

```sql
config timeframe = 7d
| dataset = issues
| comp count() as cnt by xdm.issue.severity
| sort desc cnt
| limit 10
```

## When to use

XDM-normalized severity distribution using `xdm.issue.severity` (the actual XDM path; xdm.alert.severity is the alerts-level path).

## Variations

_(No variations are documented for this entry.)_
