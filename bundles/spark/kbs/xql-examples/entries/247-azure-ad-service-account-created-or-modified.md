---
id: XQL-247-c6ad0a1a
title: Azure AD service account created or modified
category: investigation
dataset: msft_azure_ad_audit
tags:
  - preset
  - filter
  - msft_azure_ad_audit
  - source:preset
---

# Azure AD service account created or modified

**Dataset**: `msft_azure_ad_audit`

```sql
preset = msft_azure_ad_audit  // go over azure ad audit logs
| filter activityDisplayName IN ("Add service principal credentials", "Add service principal") 
  AND result = "success" // find cases where somone adds SPNs to an account
```

## When to use

Monitor service account creation and changes in service account credentials

## Variations

_(No variations are documented for this entry.)_
