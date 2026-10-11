---
id: XQL-847-c3bc070f
title: Endpoints with formatted summary string (format_string)
category: investigation
dataset: endpoints
tags:
  - filter
  - alter
  - fields
  - sort
  - limit
  - endpoints
  - format_string
---

# Endpoints with formatted summary string (format_string)

**Dataset**: `endpoints`

```sql
dataset = endpoints
| filter endpoint_status != null
| alter summary = format_string("%s (%s) - %s", endpoint_name, operating_system, endpoint_status)
| fields summary, last_seen, agent_version
| sort desc last_seen
| limit 10
```

## When to use

Per-endpoint composed summary line via `format_string("%s (%s) - %s", ...)`. Useful for one-line display in reports / chat output.

## Variations

_(No variations are documented for this entry.)_
