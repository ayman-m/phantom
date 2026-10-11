---
id: XQL-371-1afcc7f6
title: CVEs Related to a Specific Host
category: investigation
dataset: va_cves
tags:
  - arrayexpand
  - filter
  - sort
  - va_cves
  - source:dataset
---

# CVEs Related to a Specific Host

**Dataset**: `va_cves`

```sql
dataset = va_cves |
arrayexpand affected_hosts |
filter affected_hosts contains $host |
sort desc severity_score
```

## When to use

Lists CVEs related to a specific host

## Variations

_(No variations are documented for this entry.)_
