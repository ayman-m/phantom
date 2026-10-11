---
id: XQL-806-b0c49191
title: Critical CVEs in catalog
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

# Critical CVEs in catalog

**Dataset**: `va_cves`

```sql
dataset = va_cves
| filter severity = "CRITICAL"
| fields cve_id, severity, severity_score, description, publication_date
| sort desc severity_score
| limit 10
```

## When to use

Critical-severity CVEs sorted by CVSS-equivalent severity score. The `severity` field is plain string (CRITICAL/HIGH/MEDIUM/LOW).

## Variations

_(No variations are documented for this entry.)_
