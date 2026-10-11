---
id: XQL-375-123aeadd
title: Geolocations Specific User Logged in From in Last Month
category: investigation
dataset: authentication_story
tags:
  - config
  - preset
  - filter
  - comp
  - arrayexpand
  - authentication_story
  - source:preset
---

# Geolocations Specific User Logged in From in Last Month

**Dataset**: `authentication_story`

```sql
config timeframe = 30d
| preset = authentication_story
| filter auth_identity contains $user and action_country != "-"
| comp values(action_country) as action_country by auth_client, auth_identity , auth_identity_display_name , auth_service
| arrayexpand action_country
```

## When to use

Lists the geolocations that a specific user logged in from in the last month

## Variations

_(No variations are documented for this entry.)_
