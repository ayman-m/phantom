---
id: XQL-605-441f7226
title: Correlation Rules with the Highest Issue Count in Last 7 Days
category: investigation
dataset: issues
tags:
  - config
  - fields
  - join
  - issues
  - source:dataset
---

# Correlation Rules with the Highest Issue Count in Last 7 Days

**Dataset**: `issues`

```sql
config timeframe = 7D
| dataset = issues
| fields xdm.issue.detection.rule_id , xdm.issue.name
|  join type = inner (dataset = correlations_auditing ) as join_issues join_issues.rule_id  = to_integer(xdm.issue.detection.rule_id )
```

## When to use

Lists the correlation rules generating the most Issues in the last 7 days

## Variations

_(No variations are documented for this entry.)_
