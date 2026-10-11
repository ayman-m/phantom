---
id: XQL-016-e7f6dd05
title: Gitlab - User Permission Changed
category: investigation
dataset: gitlab_gitlab_raw
tags:
  - fields
  - filter
---

# Gitlab - User Permission Changed

**Dataset**: `gitlab_gitlab_raw`

```sql
datamodel dataset = gitlab_gitlab_raw
| fields _time
,xdm.event.id
,xdm.source.user.identifier
,xdm.target.resource.id
,xdm.target.resource.type
,xdm.source.user.username
,xdm.target.resource.sub_type
,xdm.target.resource.name
,xdm.event.description
,xdm.source.ipv4
,xdm.target.resource_before.value
,xdm.target.resource.value
,xdm.event.operation
,xdm.event.type
,xdm.event.operation_sub_type
| filter xdm.event.operation = "change_access_level" and xdm.target.resource_before.value = "Guest" and xdm.target.resource.value = "Owner"
```

## When to use

Gitlab - User Permission Changed. XDM-normalized query over `gitlab_gitlab_raw`, filtered on `xdm.event.operation = "change_access_level" and xdm.target.resource_before.value = "Guest" and xdm.target.resource.value = "Owner"`. Uses stages: `fields`, `filter`.

## Variations

_(No variations are documented for this entry.)_
