---
id: XQL-796-387ffea5
title: Persistence-tactic alerts (30d, TA0003)
category: detection
dataset: alerts
tags:
  - filter
  - fields
  - sort
  - limit
  - alerts
  - mitre
  - TA0003
---

# Persistence-tactic alerts (30d, TA0003)

**Dataset**: `alerts`

```sql
config timeframe = 30d
| dataset = alerts
| filter mitre_attack_tactic contains "TA0003" or mitre_attack_tactic contains "Persistence"
| fields _time, host_name, alert_name, severity, mitre_attack_technique
| sort desc _time
| limit 10
```

## When to use

Alerts mapped to MITRE TA0003 Persistence. Captures registry/service/scheduled-task/WMI persistence detections.

## Variations

_(No variations are documented for this entry.)_
