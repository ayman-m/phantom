---
id: XQL-033-7a41da60
title: Create alert for new/unassigned IT incidents
category: general
dataset: incidents
tags:
  - filter
---

# Create alert for new/unassigned IT incidents

**Dataset**: `incidents`

```sql
dataset = incidents
| filter incident_domain = "DOMAIN_IT"
| filter status = ENUM.NEW
```

## When to use

Create alert for new/unassigned IT incidents. Queries the `incidents` dataset directly, filtered on `incident_domain = "DOMAIN_IT"`. Uses stages: `filter`.

## Variations

_(No variations are documented for this entry.)_
