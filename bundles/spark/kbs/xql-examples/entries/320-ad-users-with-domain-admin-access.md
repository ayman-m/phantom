---
id: XQL-320-1d2fa544
title: AD Users with Domain Admin Access
category: investigation
dataset: ad_users
tags:
  - preset
  - filter
  - comp
  - ad_users
  - source:preset
---

# AD Users with Domain Admin Access

**Dataset**: `ad_users`

```sql
preset = ad_users
| filter netbios_domain in($domain)
|filter member_of contains "Domain Admins"
| comp count(full_user_name) as admins, values(full_user_name) as user_name
```

## When to use

Counts Active Directory users with domain admin privileges to help identify potential security risks by highlighting accounts with elevated permissions

## Variations

_(No variations are documented for this entry.)_
