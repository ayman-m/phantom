---
id: XQL-805-9f282858
title: Top 10 CVEs by affected-host count
category: investigation
dataset: va_cves
tags:
  - filter
  - fields
  - sort
  - limit
  - va_cves
  - vulnerability
---

# Top 10 CVEs by affected-host count

**Dataset**: `va_cves`

```sql
dataset = va_cves
| filter affected_hosts_count != null
| fields cve_id, severity, affected_hosts_count, severity_score, description
| sort desc affected_hosts_count
| limit 10
```

## When to use

Most-impacted CVEs by affected-host count. Uses the live tenant's `affected_hosts_count` field directly — no aggregation needed.

## Variations

_(No variations are documented for this entry.)_
