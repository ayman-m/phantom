---
id: XQL-623-051a4307
title: Container Instances with AI Packages
category: investigation
dataset: asset_inventory
tags:
  - filter
  - join
  - alter
  - fields
  - windowcomp
  - comp
  - asset_inventory
  - source:dataset
  - AI packages
---

# Container Instances with AI Packages

**Dataset**: `asset_inventory`

```sql
dataset = asset_inventory
| filter xdm.asset.type.category = "Container Instance"
| join type = inner (dataset = ai_packages | alter ts = to_timestamp(floor(scan_time), "MILLIS") | fields strong_id, related_asset_id, _name as package_name, _version as version, ts as scan_time, ai_categories, ai_technologies, package_manager, related_asset_provider | windowcomp row_number() by related_asset_id, strong_id sort desc scan_time as row_num | filter row_num = 1 | comp count() as ai_package_count by related_asset_id, related_asset_provider) as pkg pkg.related_asset_id = xdm.asset.id
| fields xdm.asset.id as asset_id, xdm.asset.name as asset_name, xdm.asset.type.category as asset_category, xdm.asset.type.name as asset_type, xdm.asset.provider as provider, xdm.asset.cloud.region as region, xdm.asset.first_observed as first_observed, ai_package_count
```

## When to use

Lists all container instances that have at least one AI package installed and shows the total AI package count per instance

## Variations

_(No variations are documented for this entry.)_
