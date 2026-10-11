---
id: XQL-259-6918e64e
title: Last 10 countries performed cloud activities
category: investigation
dataset: cloud_audit_logs
tags:
  - iploc
  - comp
  - sort
  - limit
  - cloud_audit_logs
  - source:dataset
---

# Last 10 countries performed cloud activities

**Dataset**: `cloud_audit_logs`

```sql
// Cloud provider - Any
// Cloud component - Any
config case_sensitive = false 
| dataset = cloud_audit_logs
| iploc caller_ip loc_country as ConnectionCountry // Extract the location of the IP Address
| comp count(_time ) as remotelocations by ConnectionCountry // Count the number of connections from remote countries
| sort asc remotelocations 
| limit 10 // Show the least countries performing actions on the cloud tenants
```

## When to use

Displays last 10 countries where activities were performed in the cloud.

## Variations

_(No variations are documented for this entry.)_
