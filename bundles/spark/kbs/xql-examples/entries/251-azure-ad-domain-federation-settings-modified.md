---
id: XQL-251-250f7148
title: Azure AD domain federation settings modified
category: investigation
dataset: msft_azure_ad_audit
tags:
  - preset
  - filter
  - msft_azure_ad_audit
  - source:preset
---

# Azure AD domain federation settings modified

**Dataset**: `msft_azure_ad_audit`

```sql
preset = msft_azure_ad_audit  // go over azure ad audit logs
| filter activityDisplayName = "Set federation settings on domain"
```

## When to use

Displays new trusts or certificates that has been added to the domain federation

## Variations

_(No variations are documented for this entry.)_
