---
id: XQL-249-a16557f3
title: Azure AD custom unverified domain was added
category: investigation
dataset: msft_azure_ad_audit
tags:
  - preset
  - filter
  - msft_azure_ad_audit
  - source:preset
---

# Azure AD custom unverified domain was added

**Dataset**: `msft_azure_ad_audit`

```sql
preset = msft_azure_ad_audit // go over azure ad audit logs
| filter activityDisplayName = "Add unverified domain" AND result = "success"  // find cases where someone added a custom domain to the azuread env
```

## When to use

Displays unverified domains added to Azure AD

## Variations

_(No variations are documented for this entry.)_
