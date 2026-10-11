---
id: XQL-263-21e87f62
title: Administrative group modification
category: investigation
dataset: msft_azure_ad_audit_raw
tags:
  - filter
  - msft_azure_ad_audit_raw
  - source:dataset
---

# Administrative group modification

**Dataset**: `msft_azure_ad_audit_raw`

```sql
// Cloud provider - Azure
// Cloud component - Authorization\Group Management
config case_sensitive = false | dataset = msft_azure_ad_audit_raw 
| filter activityDisplayName contains "Add member to group" and targetResources in ("admin*") // Search for users added to administrative group
```

## When to use

Displays users added to the administrative group.

## Variations

_(No variations are documented for this entry.)_
