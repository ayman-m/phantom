---
id: XQL-184-ab8554ef
title: QE - Quick Summary of Odd Accounts
category: investigation
dataset: host_inventory_users
tags:
  - preset
  - fields
  - comp
  - filter
  - host_inventory_users
  - source:preset
  - allos
  - noca
  - panwopen
  - poc
  - dashboard
---

# QE - Quick Summary of Odd Accounts

**Dataset**: `host_inventory_users`

```sql
//Title: Quick Summary of Odd Accounts
//Description: Uses the host inventory users preset to provide a quick summary of password settings/info and account disabled status.
//Dataset: host_inventory_users
//Requirements: Systems must be in an agent policy with Host Insights enabled.  Host Insights is enabled by default for tenants deployed for Unit42 engagments 
//Filter: None
//Tags: AllOS,NoCA,PANWOpen,POC,Dashboard

//Turn off case sensitivity, set timeframe to last 30 days
config case_sensitive = false timeframe = 30d 

// Use data from the Host Inventory: Users preset
| preset = host_inventory_users

//Returning relevant fields
//| fields endpoint_name, name, full_name , account_type , disabled , password_changeable , password_required , password_expired , user_domain 

//Use this section to aggregate data for CA analysis, turn off for reporting
//Option 1: List users and details about each user, including how a count of many endpoints the user is on
| comp count_distinct(endpoint_name) by name, full_name, user_domain, disabled, password_changeable, password_expired, password_required, account_type
//Option 2: List users and account disabled status only, including how a count of many endpoints the user is on
//| comp count_distinct(endpoint_name), values(full_name) by name,  disabled

//Use this section to put finding in report format for CA, replace [Finding] with what you would like to report (wildcards* accepted), field for filtering can be changed
//| filter name in ["Finding", "Finding"]
//| fields endpoint_name, name, full_name , account_type , disabled , password_changeable , password_required , password_expired , user_domain
```

## When to use

Uses the host inventory users preset to provide a quick summary of password settings/info and account disabled status.

## Variations

_(No variations are documented for this entry.)_
