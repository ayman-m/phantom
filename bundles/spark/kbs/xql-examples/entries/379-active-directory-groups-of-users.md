---
id: XQL-379-f4644c52
title: Active Directory Groups of Users
category: investigation
dataset: pan_dss_raw
tags:
  - filter
  - fields
  - arrayexpand
  - pan_dss_raw
  - source:dataset
---

# Active Directory Groups of Users

**Dataset**: `pan_dss_raw`

```sql
dataset = pan_dss_raw
| filter netbios_and_sam_account_name contains $user or upn contains $user or sam_account_name contains $user
| fields  display_name , security_groups , sam_account_name , upn ,netbios_and_sam_account_name , last_logon_timestamp , guid , dn,ou
| arrayexpand security_groups
```

## When to use

Lists all the Active Direcory groups a user is a member of

## Variations

_(No variations are documented for this entry.)_
