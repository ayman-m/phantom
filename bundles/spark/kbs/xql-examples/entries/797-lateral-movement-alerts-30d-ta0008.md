---
id: XQL-797-fc7bfe5a
title: Lateral-movement alerts (30d, TA0008)
category: detection
dataset: alerts
tags:
  - filter
  - fields
  - sort
  - limit
  - alerts
  - mitre
  - TA0008
---

# Lateral-movement alerts (30d, TA0008)

**Dataset**: `alerts`

```sql
config timeframe = 30d
| dataset = alerts
| filter mitre_attack_tactic contains "TA0008" or mitre_attack_tactic contains "Lateral"
| fields _time, host_name, alert_name, severity, mitre_attack_technique
| sort desc _time
| limit 10
```

## When to use

Lateral-movement detections (MITRE TA0008). PsExec, WinRM abuse, remote service creation, RDP, SMB.

## Variations

_(No variations are documented for this entry.)_
