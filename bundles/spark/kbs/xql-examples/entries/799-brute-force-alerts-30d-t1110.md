---
id: XQL-799-ff0abccc
title: Brute-force alerts (30d, T1110)
category: detection
dataset: alerts
tags:
  - filter
  - fields
  - sort
  - limit
  - alerts
  - T1110
---

# Brute-force alerts (30d, T1110)

**Dataset**: `alerts`

```sql
config timeframe = 30d
| dataset = alerts
| filter lowercase(alert_name) contains "brute" or lowercase(alert_name) contains "password spray" or lowercase(alert_name) contains "failed login" or mitre_attack_technique contains "T1110"
| fields _time, host_name, alert_name, severity, user_name
| sort desc _time
| limit 10
```

## When to use

Brute-force + password-spray detections (MITRE T1110). Common against external-facing services + privileged accounts.

## Variations

_(No variations are documented for this entry.)_
