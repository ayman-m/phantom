---
id: XQL-477-ebf39f60
title: Vulnerabilities Relating to Android and Linux Operating Systems
category: investigation
dataset: va_cves
tags:
  - filter
  - fields
  - va_cves
  - source:dataset
---

# Vulnerabilities Relating to Android and Linux Operating Systems

**Dataset**: `va_cves`

```sql
dataset = va_cves
| filter os_type in (ENUM.LINUX, ENUM.ANDROID) and (type = ENUM.APPLICATION_AND_OS)
| fields affected_hosts, affected_hosts_count, affected_products, name, description, *
```

## When to use

Lists the vulnerabilities that were found on an Android or Linux operating system for the vulnerability type called "APPLICATION_AND_OS"

## Variations

_(No variations are documented for this entry.)_
