---
id: XQL-804-145174fa
title: Critical issues with platform-severity (7d)
category: detection
dataset: issues
tags:
  - filter
  - fields
  - sort
  - limit
  - issues
  - xdm
---

# Critical issues with platform-severity (7d)

**Dataset**: `issues`

```sql
config timeframe = 7d
| dataset = issues
| filter xdm.issue.severity = "SEV_040_HIGH" or xdm.issue.severity = "SEV_050_CRITICAL"
| fields _time, xdm.issue.name, xdm.issue.severity, xdm.issue.platform_severity
| sort desc _time
| limit 10
```

## When to use

High/Critical XDM-normalized issues. XDM severity is `SEV_NNN_LABEL` strings — note the prefix when filtering.

## Variations

_(No variations are documented for this entry.)_
