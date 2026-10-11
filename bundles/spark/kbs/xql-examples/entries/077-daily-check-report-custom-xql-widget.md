---
id: XQL-077-e5ae180e
title: Daily Check Report - Custom XQL Widget
category: investigation
dataset: management_auditing
tags:
  - fields
  - filter
  - sort
---

# Daily Check Report - Custom XQL Widget

**Dataset**: `management_auditing`

```sql
dataset = management_auditing
| filter (`management_auditing_type` = MANAGEMENT_AUDIT_BROKER_VMS)
| fields _time, description, subtype
| sort desc _time
```

## When to use

Daily Check Report - Custom XQL Widget. Queries the `management_auditing` dataset directly, filtered on `(`management_auditing_type` = MANAGEMENT_AUDIT_BROKER_VMS)`. Uses stages: `filter`, `fields`, `sort`.

## Variations

_(No variations are documented for this entry.)_
