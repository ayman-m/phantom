---
id: XQL-332-241795ac
title: Data Model Rules Errors
category: investigation
dataset: parsing_rules_errors
tags:
  - filter
  - parsing_rules_errors
  - source:dataset
---

# Data Model Rules Errors

**Dataset**: `parsing_rules_errors`

```sql
dataset = parsing_rules_errors
| filter rule_type contains "Data Model Rule"
```

## When to use

Lists the errors related to the Cortex Data Model (XDM) rules to help explain where data can be failing to align with the expected schema and require further analysis

## Variations

_(No variations are documented for this entry.)_
