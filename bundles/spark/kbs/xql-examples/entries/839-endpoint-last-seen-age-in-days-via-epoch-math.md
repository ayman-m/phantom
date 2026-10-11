---
id: XQL-839-3ec02fb7
title: Endpoint last-seen age in days via epoch math
category: investigation
dataset: endpoints
tags:
  - filter
  - alter
  - fields
  - sort
  - limit
  - endpoints
  - to_epoch
  - math
---

# Endpoint last-seen age in days via epoch math

**Dataset**: `endpoints`

```sql
dataset = endpoints
| filter last_seen != null
| alter age_seconds = divide(subtract(to_epoch(current_time(), "SECONDS"), to_epoch(last_seen, "SECONDS")), 1)
| alter age_days = floor(divide(age_seconds, 86400))
| fields endpoint_name, last_seen, age_days, endpoint_status
| sort desc age_days
| limit 10
```

## When to use

Endpoint last-seen age in days. `to_epoch(timestamp, 'SECONDS')` converts both `current_time()` and `last_seen` to epoch seconds; subtraction + floor + divide-by-86400 gives integer days. Robust pattern for date-arithmetic on date-typed fields.

## Variations

_(No variations are documented for this entry.)_
