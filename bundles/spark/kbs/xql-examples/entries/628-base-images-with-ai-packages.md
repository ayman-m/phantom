---
id: XQL-628-12d970b1
title: Base Images with AI Packages
category: investigation
dataset: asset_inventory
tags:
  - filter
  - alter
  - join
  - fields
  - windowcomp
  - comp
  - asset_inventory
  - source:dataset
  - AI packages
---

# Base Images with AI Packages

**Dataset**: `asset_inventory`

```sql
dataset = asset_inventory
| filter xdm.asset.type.category = "Container Image"
| alter is_base_image = uppercase(coalesce(json_extract_scalar(xdm.asset.raw_fields, "$.CWP.is_base_image"), "false"))
| filter is_base_image = "TRUE"
| join type = inner (dataset = ai_packages | alter ts = to_timestamp(floor(scan_time), "MILLIS") | fields strong_id, related_asset_id, _name as package_name, _version as version, ts as scan_time, ai_categories, ai_technologies, package_manager, related_asset_provider | windowcomp row_number() by related_asset_id, strong_id sort desc scan_time as row_num | filter row_num = 1 | comp count() as ai_package_count by related_asset_id, related_asset_provider) as pkg pkg.related_asset_id = xdm.asset.id
| fields xdm.asset.id as asset_id, xdm.asset.name as asset_name, xdm.asset.type.category as asset_category, xdm.asset.type.name as asset_type, xdm.asset.provider as provider, xdm.asset.cloud.region as region, xdm.asset.first_observed as first_observed, is_base_image, ai_package_count
```

## When to use

Lists all base container images that have at least one AI package installed and shows the total AI package count per image

## Variations

_(No variations are documented for this entry.)_
