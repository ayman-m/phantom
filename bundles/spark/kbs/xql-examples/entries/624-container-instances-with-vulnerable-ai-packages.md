---
id: XQL-624-493fdb56
title: Container Instances with Vulnerable AI Packages
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

# Container Instances with Vulnerable AI Packages

**Dataset**: `asset_inventory`

```sql
dataset = asset_inventory
| filter xdm.asset.type.category = "Container Instance"
| join type = inner (dataset = ai_packages | alter ts = to_timestamp(floor(scan_time), "MILLIS") | fields strong_id, related_asset_id, _name as package_name, _version as version, ts as scan_time, related_asset_provider | windowcomp row_number() by related_asset_id, strong_id sort desc scan_time as row_num | filter row_num = 1 | join type = inner (dataset = findings | filter xdm.finding.category = "VULNERABILITY" and xdm.finding.asset_class = "Compute" and xdm.finding.is_active = true | fields xdm.finding.asset_id as fnd_asset_id, xdm.software_package.id as fnd_package_name, xdm.software_package.version as fnd_version, xdm.vulnerability.severity as vuln_severity | comp count() as vuln_count by fnd_asset_id, fnd_package_name, fnd_version) as fnd fnd.fnd_asset_id = related_asset_id and lowercase(fnd.fnd_package_name) = lowercase(package_name) and fnd.fnd_version = version | comp sum(vuln_count) as total_vulnerabilities by related_asset_id, related_asset_provider) as pkg pkg.related_asset_id = xdm.asset.id
| fields xdm.asset.id as asset_id, xdm.asset.name as asset_name, xdm.asset.type.category as asset_category, xdm.asset.type.name as asset_type, xdm.asset.provider as provider, xdm.asset.cloud.region as region, xdm.asset.first_observed as first_observed, total_vulnerabilities
```

## When to use

Lists all container instances that have at least one AI package with an active vulnerability and shows the total vulnerability count per instance

## Variations

_(No variations are documented for this entry.)_
