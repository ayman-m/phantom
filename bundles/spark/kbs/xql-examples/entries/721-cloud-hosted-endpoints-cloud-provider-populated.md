---
id: XQL-721-4ffff89f
title: Cloud-hosted endpoints (cloud_provider populated)
category: detection
dataset: endpoints
tags:
  - filter
  - fields
  - sort
  - limit
  - endpoints
  - cloud
---

# Cloud-hosted endpoints (cloud_provider populated)

**Dataset**: `endpoints`

```sql
dataset = endpoints
| filter cloud_provider != null
| fields endpoint_name, cloud_provider, cloud_region, cloud_instance_id, operating_system, endpoint_status
| sort desc cloud_provider
| limit 10
```

## When to use

Identifies endpoints hosted in cloud providers (AWS, Azure, GCP). Useful for cloud-workload visibility + correlating with cloud-side audit events.

## Variations

_(No variations are documented for this entry.)_
