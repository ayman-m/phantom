---
id: XQL-798-0ee9739c
title: Exfiltration-tactic alerts (30d, TA0010)
category: detection
dataset: alerts
tags:
  - filter
  - fields
  - sort
  - limit
  - alerts
  - mitre
  - TA0010
---

# Exfiltration-tactic alerts (30d, TA0010)

**Dataset**: `alerts`

```sql
config timeframe = 30d
| dataset = alerts
| filter mitre_attack_tactic contains "TA0010" or mitre_attack_tactic contains "Exfiltration"
| fields _time, host_name, alert_name, severity, mitre_attack_technique
| sort desc _time
| limit 10
```

## When to use

Exfiltration detections (MITRE TA0010). Bulk uploads, archive activity, anomalous outbound.

## Variations

_(No variations are documented for this entry.)_
