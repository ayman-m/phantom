---
id: XQL-747-e074e6b8
title: Alerts with file_macro_sha256 extracted (30d)
category: investigation
dataset: alerts
tags:
  - filter
  - fields
  - sort
  - limit
  - alerts
---

# Alerts with file_macro_sha256 extracted (30d)

**Dataset**: `alerts`

```sql
config timeframe = 30d
| dataset = alerts
| filter file_macro_sha256 != null
| fields _time, host_name, alert_name, severity, file_macro_sha256, file_path
| sort desc _time
| limit 10
```

## When to use

Alerts that include a macro-bearing file SHA256. Useful for office-macro-attack triage — pull the hash, the host, and the file path.

## Variations

_(No variations are documented for this entry.)_
