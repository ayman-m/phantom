---
id: XQL-248-e687d2f5
title: Azure AD application has been shared with additional tenants
category: investigation
dataset: msft_azure_ad_audit
tags:
  - preset
  - filter
  - msft_azure_ad_audit
  - source:preset
---

# Azure AD application has been shared with additional tenants

**Dataset**: `msft_azure_ad_audit`

```sql
preset = msft_azure_ad_audit  // go over azure ad audit logs
| filter activityDisplayName = "Update application"
  AND operationType="Update"
  and result="success"
  and modifiedDisplayName = "AvailableToOtherTenants"  // find cases where someone grants permission to access an app from another azuread tenant
```

## When to use

Displayes changes in available tenants that are granted to access the specific application

## Variations

_(No variations are documented for this entry.)_
