---
id: XQL-020-8e5c8b3f
title: NUC Agent Update Script
category: investigation
dataset: endpoints
tags:
  - alter
  - fields
  - filter
---

# NUC Agent Update Script

**Dataset**: `endpoints`

```sql
dataset = endpoints
| filter group_names in ("NUCs") and last_upgrade_status = "COMPLETED_SUCCESSFULLY" and endpoint_status = ENUM.CONNECTED
| alter ct = current_time()
| alter diff_in_mins = timestamp_diff(ct, last_upgrade_status_time, "MINUTE")
| filter diff_in_mins < 59
| fields diff_in_mins, endpoint_status, endpoint_id, endpoint_name, group_names, agent_version, ip_address , mac_address, last_upgrade_status_time
```

## When to use

NUC Agent Update Script. Queries the `endpoints` dataset directly, filtered on `group_names in ("NUCs") and last_upgrade_status = "COMPLETED_SUCCESSFULLY" and endpoint_status = ENUM.CONNECTED`. Uses stages: `filter`, `alter`, `fields`.

## Variations

_(No variations are documented for this entry.)_
