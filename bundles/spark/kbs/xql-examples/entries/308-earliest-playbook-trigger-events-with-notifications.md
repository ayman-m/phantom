---
id: XQL-308-65072ec9
title: Earliest Playbook Trigger Events with Notifications
category: investigation
dataset: management_auditing
tags:
  - alter
  - filter
  - comp
  - management_auditing
  - source:dataset
---

# Earliest Playbook Trigger Events with Notifications

**Dataset**: `management_auditing`

```sql
dataset = management_auditing
| alter xql_category = "XSIAM Management Audit Alert"
| alter notify_engineering = true
| alter skip_execution = true
| filter management_auditing_type in("PLAYBOOK_TRIGGERS")
| comp earliest(timestamp) as timestamp, count(timestamp) as count by description, subtype, email, user_name, xql_category, notify_engineering, skip_execution
```

## When to use

Lists the earliest occurrences of playbook trigger events and details how many had notifications for engineering enabled and execution skipped

## Variations

_(No variations are documented for this entry.)_
