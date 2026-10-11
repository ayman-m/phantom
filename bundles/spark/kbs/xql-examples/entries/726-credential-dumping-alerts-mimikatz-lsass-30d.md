---
id: XQL-726-3edd6341
title: Credential-dumping alerts (Mimikatz, LSASS) (30d)
category: detection
dataset: alerts
tags:
  - filter
  - fields
  - sort
  - limit
  - alerts
  - T1003
---

# Credential-dumping alerts (Mimikatz, LSASS) (30d)

**Dataset**: `alerts`

```sql
config timeframe = 30d
| dataset = alerts
| filter lowercase(alert_name) contains "mimikatz" or lowercase(alert_name) contains "lsass" or lowercase(description) contains "mimikatz" or lowercase(description) contains "credential"
| fields _time, host_name, severity, alert_name, description
| sort desc _time
| limit 10
```

## When to use

Credential-extraction-related alerts. MITRE T1003 family — Mimikatz, LSASS memory access, credential dumping. Returns hits across the alert_name + description for broad coverage.

## Variations

_(No variations are documented for this entry.)_
