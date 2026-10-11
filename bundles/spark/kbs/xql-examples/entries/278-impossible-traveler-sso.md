---
id: XQL-278-d7ab7d20
title: Impossible traveler - sso
category: investigation
dataset: authentication_story
tags:
  - preset
  - filter
  - comp
  - alter
  - authentication_story
  - source:preset
---

# Impossible traveler - sso

**Dataset**: `authentication_story`

```sql
preset = authentication_story
| filter action_country != "" and action_country != "-" AND auth_outcome = "SUCCESS" AND action_country != null
| comp values(action_country) as countries by auth_identity
| alter count_distinct_action_country = array_length(countries)
| filter count_distinct_action_country > 1
```

## When to use

Display potential Impossible traveler authenticating sso from more than one country.Recommended to run hourly

## Variations

_(No variations are documented for this entry.)_
