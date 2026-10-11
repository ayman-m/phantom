---
id: XQL-300-42fb5e3c
title: Correlation Rules that Failed to Run
category: investigation
dataset: correlations_auditing
tags:
  - filter
  - fields
  - sort
  - correlations_auditing
  - source:dataset
---

# Correlation Rules that Failed to Run

**Dataset**: `correlations_auditing`

```sql
dataset = correlations_auditing
| filter status ="Error"
| fields _time , name , rule_id ,status , failure_reason ,  retry_attempts , query_start_time , query_end_time,*
| sort desc _time
```

## When to use

Lists the correlation rules that failed to run, and provides the failure reason, retry attempts, and timestamps of the query

## Variations

_(No variations are documented for this entry.)_
