---
id: XQL-222-728bdf44
title: Top 10 Users failing to authenticate from multiple locations
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - comp
  - sort
  - limit
  - xdr_data
  - source:dataset
---

# Top 10 Users failing to authenticate from multiple locations

**Dataset**: `xdr_data`

```sql
// NOTE: Requires authentication data from Azure, OKTA, Ping
 dataset = xdr_data // Using the XDR dataset
 | filter event_type = ENUM.STORY and auth_identity_display_name != null and auth_outcome  != "SUCCESS" // Filtering for cases where a user failed to authenticate
 | fields auth_identity_display_name as user, auth_identity as email, auth_client as source // Selecting the username, email and the auth_client which contains the IP from which the user failed to authenticate
 | comp count_distinct(source) as counter by user, email // Counting the unique IPs per user/email
 | sort desc counter // Sorting in descending order
 | limit 10 // Showing only the top 10
```

## When to use

Identify the top 10 users failing to authenticate from multiple unique IP addresses, using data from Azure AD, Okta or PingOne

## Variations

_(No variations are documented for this entry.)_
