---
id: XQL-381-67fb44cd
title: Changes Made to User Permission Levels in Last Month on the Cloud
category: investigation
dataset: msft_azure_ad_audit_raw
tags:
  - config
  - filter
  - alter
  - fields
  - union
  - msft_azure_ad_audit_raw
  - source:dataset
---

# Changes Made to User Permission Levels in Last Month on the Cloud

**Dataset**: `msft_azure_ad_audit_raw`

```sql
config timeframe = 30d
| dataset = msft_azure_ad_audit_raw
| filter category = "RoleManagement" and activityDisplayName = "Add member to role" and result in ("failure", "success")
| alter user = initiatedBy -> user.userPrincipalName, app = initiatedBy -> app.displayName
| alter source_user= coalesce(user,app), role_name= json_extract_scalar(targetResources , "$.0.modifiedProperties.1.newValue") , target_user= json_extract_scalar(targetResources , "$.0.userPrincipalName")
| filter target_user = $user
| filter app in (null,"Microsoft Office 365 Portal") or (app="MS-PIM")
| fields source_user, role_name,target_user, operationType ,activityDisplayName ,category , result , *
| union (dataset = amazon_aws_raw
| filter eventName ~= "Attach\w+Policy$"
| alter roleName = json_extract_scalar(requestParameters , "$.policyArn") | filter requestParameters -> userName = $user)
```

## When to use

Lists Azure AD and AWS role management events in the last month, where the user's permissions are changed

## Variations

_(No variations are documented for this entry.)_
