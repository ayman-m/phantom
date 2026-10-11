---
id: XQL-246-cc4d1635
title: Mail read permissions added to Account
category: investigation
dataset: msft_azure_ad_audit
tags:
  - preset
  - filter
  - msft_azure_ad_audit
  - source:preset
---

# Mail read permissions added to Account

**Dataset**: `msft_azure_ad_audit`

```sql
preset = msft_azure_ad_audit // go over azure ad audit logs
| filter activityDisplayName IN ("Add app role assignment to service principal", "Add delegated permission grant", "Add application" ) and
         modifiedPropertyNewValue ~= "(Mail.Read|Mail.ReadWrite)" and 
         modifiedPropertyOldValue not contains "Mail.Read" // find cases where mail read was added as a permission to another account
```

## When to use

Displayes accounts that was granted Mail read permissions

## Variations

_(No variations are documented for this entry.)_
