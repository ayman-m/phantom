---
id: XQL-598-8d6e66e6
title: K8 Endpoint Data
category: investigation
dataset: endpoints
tags:
  - filter
  - alter
  - fields
  - endpoints
  - source:dataset
---

# K8 Endpoint Data

**Dataset**: `endpoints`

```sql
dataset = endpoints 
| filter cloud_info != null
| alter 
    // Cluster identification fields
    node_name = json_extract_scalar(cloud_info, "$.name"),
    k8_provider = json_extract_scalar(cloud_info, "$.cloud_provider"),
    vm_scale_set_name = json_extract_scalar(cloud_info, "$.raw.compute.vmScaleSetName"),
    k8_region = json_extract_scalar(cloud_info, "$.region"),
    geo_region = json_extract_scalar(cloud_info, "$.geo_region"),
    project_id = json_extract_scalar(cloud_info, "$.project_id"),
    sub_region = json_extract_scalar(cloud_info, "$.sub_region"),
    cluster_resource_suffix = arrayindex(regextract(json_extract_scalar(cloud_info, "$.raw.compute.tags"),"aks-managed-resourceNameSuffix:([^;]+)"),0),
    node_pool_name = arrayindex(regextract(json_extract_scalar(cloud_info, "$.raw.compute.tags"),"aks-managed-poolName:([^;]+)"),0),
    kubernetes_version = arrayindex(regextract(json_extract_scalar(cloud_info, "$.raw.compute.tags"),"aks-managed-orchestrator:([^;]+)"),0),
    
    //Compute section
    vm_id = json_extract_scalar(cloud_info, "$.raw.compute.vmId"),
    vm_size = json_extract_scalar(cloud_info, "$.raw.compute.vmSize"),
    os_type = json_extract_scalar(cloud_info, "$.raw.compute.osType"),
    location = json_extract_scalar(cloud_info, "$.raw.compute.location"),
    version = json_extract_scalar(cloud_info, "$.raw.compute.version"),
    computer_name = json_extract_scalar(cloud_info, "$.raw.compute.osProfile.computerName"),
    admin_username = json_extract_scalar(cloud_info, "$.raw.compute.osProfile.adminUsername"),
    disable_password_auth = json_extract_scalar(cloud_info, "$.raw.compute.osProfile.disablePasswordAuthentication"),
    subscription_id = json_extract_scalar(cloud_info, "$.raw.compute.subscriptionId"),
    resource_group = json_extract_scalar(cloud_info, "$.raw.compute.resourceGroupName"),
    platform_fault_domain = json_extract_scalar(cloud_info, "$.raw.compute.platformFaultDomain"),
    platform_update_domain = json_extract_scalar(cloud_info, "$.raw.compute.platformUpdateDomain"),
    placement_group_id = json_extract_scalar(cloud_info, "$.raw.compute.placementGroupId"),
    azure_environment = json_extract_scalar(cloud_info, "$.raw.compute.azEnvironment"),
    
    // Storage profile section
    os_disk_name = json_extract_scalar(cloud_info, "$.raw.compute.storageProfile.osDisk.name"),
    os_disk_size_gb = json_extract_scalar(cloud_info, "$.raw.compute.storageProfile.osDisk.diskSizeGB"),
    os_disk_caching = json_extract_scalar(cloud_info, "$.raw.compute.storageProfile.osDisk.caching"),
    managed_disk_id = json_extract_scalar(cloud_info, "$.raw.compute.storageProfile.osDisk.managedDisk.id"),
    managed_disk_type = json_extract_scalar(cloud_info, "$.raw.compute.storageProfile.osDisk.managedDisk.storageAccountType"),
    image_reference_id = json_extract_scalar(cloud_info, "$.raw.compute.storageProfile.imageReference.id"),
    image_exact_version = json_extract_scalar(cloud_info, "$.raw.compute.storageProfile.imageReference.exactVersion"),
    
    // Network section
    mac_address = json_extract_scalar(cloud_info, "$.raw.network.interface[0].macAddress"),
    subnet_address = json_extract_scalar(cloud_info, "$.raw.network.interface[0].ipv4.subnet[0].address"),
    subnet_prefix = json_extract_scalar(cloud_info, "$.raw.network.interface[0].ipv4.subnet[0].prefix"),
    
    // Security section
    encryption_at_host = json_extract_scalar(cloud_info, "$.raw.compute.securityProfile.encryptionAtHost"),
    secure_boot_enabled = json_extract_scalar(cloud_info, "$.raw.compute.securityProfile.secureBootEnabled"),
    virtual_tpm_enabled = json_extract_scalar(cloud_info, "$.raw.compute.securityProfile.virtualTpmEnabled"),
    
    // Tags as arrays
    tags = json_extract(cloud_info, "$.tags"),
    compute_tags_list = json_extract(cloud_info, "$.raw.compute.tagsList"),
    
    // Resource ID
    resource_id = json_extract_scalar(cloud_info, "$.raw.compute.resourceId"),
    
    // Arrays as strings
    private_ips = json_extract(cloud_info, "$.private_ips"),
    public_ips = json_extract(cloud_info, "$.public_ips")
    
| fields 
    node_name,k8_provider,vm_scale_set_name,k8_region,cluster_resource_suffix,node_pool_name,kubernetes_version,geo_region,project_id,sub_region,vm_id,vm_size,os_type,location,version, computer_name, admin_username, disable_password_auth, subscription_id, resource_group,  platform_fault_domain, platform_update_domain, placement_group_id, azure_environment, os_disk_name, os_disk_size_gb, os_disk_caching, managed_disk_id, managed_disk_type, image_reference_id, image_exact_version, mac_address, subnet_address, subnet_prefix, encryption_at_host, secure_boot_enabled, virtual_tpm_enabled, tags, compute_tags_list, resource_id, private_ips, public_ips,
    active_directory, agent_license_type , agent_version , architecture , assigned_extensions_policy , assigned_prevention_policy , auto_upgrade_status , backup_management , cloud_id , cloud_info , cloud_license , content_auto_update , content_release_timestamp , content_rollout_delay_days_ , content_status , content_version , disabled_capabilities , domain , encryption_status , endpoint_alias , endpoint_id , endpoint_isolated , endpoint_name , endpoint_status , endpoint_type , first_seen , host_insights , install_date , installation_package , installation_type , installation_type , ip_address , ipv6_address , is_edr_enabled , is_forensics_enabled , isolation_date , kernel_version , last_certificate_enforcement_fallback , last_content_update_time , last_origin_ip , last_origin_ipv6 , last_seen , last_successful_scan , last_triage , last_upgrade_failure_reason , last_upgrade_source , last_upgrade_status_time , last_used_proxy , last_used_proxy_port , linux_operation_mode , mac_address , managed_device , manual_protection_pause , mobile_id , network_interface , network_location , operating_system , operational_status , operational_status_description , os_version , platform , product_name , proxy , scan_status , supported_version , system_uptime , tags , token_hash , user , version_type
```

## When to use

K8 Endpoint Data. Queries the `endpoints` dataset directly, filtered on `cloud_info != null`. Uses stages: `filter`, `alter`, `fields`.

## Variations

_(No variations are documented for this entry.)_
