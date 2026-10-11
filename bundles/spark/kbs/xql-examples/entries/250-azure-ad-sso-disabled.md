---
id: XQL-250-1862b8a7
title: Azure AD SSO disabled
category: investigation
dataset: msft_azure_ad_audit
tags:
  - preset
  - filter
  - msft_azure_ad_audit
  - source:preset
---

# Azure AD SSO disabled

**Dataset**: `msft_azure_ad_audit`

```sql
preset = msft_azure_ad_audit // go over azure ad audit logs
| filter activityDisplayName = "Disable Desktop Sso for a specific domain" AND result = "success"  // remove need for SSO on desktop devices
```

## When to use

Displays domains that SSO was disabled for. another authentication mechanism will be used

## Variations

_(No variations are documented for this entry.)_
