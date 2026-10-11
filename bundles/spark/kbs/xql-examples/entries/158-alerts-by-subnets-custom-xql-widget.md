---
id: XQL-158-cd9541c3
title: Alerts by Subnets - Custom XQL Widget
category: investigation
dataset: alerts
tags:
  - alter
  - comp
  - fields
  - join
  - sort
  - view
---

# Alerts by Subnets - Custom XQL Widget

**Dataset**: `alerts`

```sql
dataset = alerts
| fields alert_name , action , action_process_causality_id , action_process_instance_id , actor_causality_id , actor_process_causality_id , action_process_instance_id , agent_data_collection_status , agent_host_boot_time , agent_install_type , agent_os_sub_type , agent_version , alert_arrival_timestamp , alert_domain , alert_domain ,  alert_id , alert_source , alert_type , app_category , app_id , app_subcategory , app_technology , category , causality_actor_process_execution_time , cgo_cmd , cgo_md5 , cgo_name , cgo_path , cgo_sha256 , cgo_signature , cgo_signer , cid , cloud_identity_sub_type , cloud_identity_type , cloud_operation_type , cloud_project , cloud_provider , cloud_referenced_resource , cloud_resource_sub_type , cloud_resource_type , cluster_name , cloud_identity_sub_type , container_id , container_name , contains_featured_host , contains_featured_ip_address , contains_featured_user , country , description , destination_agent_id , destination_causality_actor_process_execution_time , destination_zone_name , dst_action_external_hostname , dst_action_external_port , dns_query_name , domain , dst_action_country , dst_action_external_hostname , dst_action_external_port , email_recipient , email_sender , email_subject , endpoint_id , event_id , event_timestamp , excluded , external_id , externally_detected_provider , file_macro_sha256 , file_md5 , file_name , file_path , file_sha256 , fw_name , fw_rule_id , fw_rule_name , fw_serial_number , host_fqdn , host_ipv6 , host_ip , host_mac_address , host_name , host_os , image_id , image_name , incident_id , initiated_by , initiator_cmd , initiator_md5 , initiator_path , initiator_pid , initiator_sha256 , initiator_signature , initiator_signer , initiator_tid , is_npcap , is_phishing , local_ip , local_ipv6 , local_port , malicious_urls , misc , mitre_attack_tactic , mitre_attack_technique , module , namespace , ngfw_vsys_name , original_tags , os_actor_causality_id , os_actor_process_causality_id , os_actor_process_instance_id , os_parent_cmd , os_parent_name , os_parent_path , os_parent_pid , os_parent_sha256 , os_parent_signature , os_parent_signer , os_parent_tid , os_parent_user_name , process_execution_signature , process_execution_signer , registry_data , registry_full_key , registry_key_name , registry_value_name , remote_host , remote_ip , remote_ipv6 , remote_port , resolution_comment , resolution_status , rule_id , severity , source_zone_name , starred , target_process_cmd , target_process_name , target_process_sha256 , url , user_agent , user_name
| alter localip = arraystring(local_ip, ", ")
| join conflict_strategy = right type = left
    (
      dataset = agentic_subnet_lookup
      | fields DHCP , FirewallZoneName , FirewallZoneType , Gateway , Location , Name , SSID , Subnet , VLAN
    )
  as subnet_lkp incidr(localip, subnet_lkp.subnet)
  | comp count () as alerts_by_location by Location | sort desc alerts_by_location
| view graph type = pie header = "Alerts by Location" xaxis = Location yaxis = alerts_by_location seriestitle("alerts_by_location","Alerts")
```

## When to use

Alerts by Subnets - Custom XQL Widget. Queries the `alerts` dataset directly. Uses stages: `fields`, `alter`, `join`, `comp`, `sort`, `view`.

## Variations

_(No variations are documented for this entry.)_
