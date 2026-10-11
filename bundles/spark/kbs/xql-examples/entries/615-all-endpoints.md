---
id: XQL-615-99a8e0ab
title: All Endpoints
category: investigation
dataset: endpoints
tags:
  - fields
  - endpoints
  - source:dataset
---

# All Endpoints

**Dataset**: `endpoints`

```sql
dataset = endpoints | fields endpoint_id , endpoint_name , endpoint_type , platform , operating_system , os_version , agent_version , agent_license_type , endpoint_status , operational_status , operational_status_description , last_seen , first_seen , endpoint_isolated , user , domain , group_names , active_directory , managed_device  , manual_protection_pause , disabled_capabilities , encryption_status , last_certificate_enforcement_fallback , scan_status , last_successful_scan , last_triage , content_status , content_version , last_content_update_time , content_auto_update , content_release_timestamp , content_rollout_delay_days_ , auto_upgrade_status , last_upgrade_status , last_upgrade_status_time , last_upgrade_source , last_upgrade_failure_reason , version_type , product_name , architecture , kernel_version , linux_operation_mode , system_uptime , host_insights , tags , network_location , network_interface , mac_address , last_origin_ip , last_origin_ipv6 , proxy , last_used_proxy , last_used_proxy_port , token_hash , endpoint_alias , golden_image_id , backup_management , assigned_prevention_policy , assigned_extensions_policy , cloud_provider , cloud_region , cloud_provider_account_id , cloud_license , cloud_id , cloud_instance_id , cloud_info , cluster_name , mobile_id
```

## When to use

All Endpoints. Queries the `endpoints` dataset directly. Uses stages: `fields`.

## Variations

_(No variations are documented for this entry.)_
