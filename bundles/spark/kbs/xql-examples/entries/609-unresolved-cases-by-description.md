---
id: XQL-609-e7f9edc7
title: Unresolved Cases by Description
category: investigation
dataset: cases
tags:
  - filter
  - fields
  - cases
  - source:dataset
---

# Unresolved Cases by Description

**Dataset**: `cases`

```sql
dataset = cases
| filter xdm.case.description in ($description) and xdm.case.status_progress not contains "RESOLVED"
| fields xdm.case.id , xdm.case.platform_severity, xdm.case.status_progress , xdm.case.description  , _insert_time, *
```

## When to use

Filters for unresolved cases according to the description

## Variations

_(No variations are documented for this entry.)_
