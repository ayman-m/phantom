---
id: XQL-010-b25a43ef
title: Corelight AI Classroom Triage Alert
category: investigation
dataset: corelight_ai_triage_raw
tags:
  - fields
  - filter
---

# Corelight AI Classroom Triage Alert

**Dataset**: `corelight_ai_triage_raw`

```sql
dataset = corelight_ai_triage_raw
| filter IR_recommendation = "ESCALATE"
| fields First_ts, Source_IP,Source_IP_range, Destination_IP, Destination_Range, alert_name, Criticality, Criticality_explanation, Source_subnet, Curriculum_question, Curriculum_explanation, IR_explanation, IR_recommendation, Traffic_direction
```

## When to use

Corelight AI Classroom Triage Alert. Queries the `corelight_ai_triage_raw` dataset directly, filtered on `IR_recommendation = "ESCALATE"`. Uses stages: `filter`, `fields`.

## Variations

_(No variations are documented for this entry.)_
