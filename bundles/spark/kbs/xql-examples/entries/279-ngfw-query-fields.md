---
id: XQL-279-eec2a30a
title: NGFW _Query_Fields
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - fields
  - panw_ngfw_traffic_raw
  - source:dataset
---

# NGFW _Query_Fields

**Dataset**: `panw_ngfw_traffic_raw`

```sql
dataset = panw_ngfw_traffic_raw | 
fields _time , _vendor , _product , location, bytes_sent, bytes_received, protocol, _collector_type , _reporting_device_ip , _reporting_device_name , source_ip, _id , _raw_json , _insert_time , _device_id , log_type, action, tunnel, app, _tag , vsys, users, is_nat, xff_ip, dest_ip, host_id, is_ipv6, log_set, to_zone, vsys_id, dest_edl, is_proxy, log_time, log_type, nat_dest, pod_name, sub_type, dest_port, dest_user, dest_uuid, flow_type, from_zone, policy_id, vsys_name, inbound_if, is_dup_log, log_source, nat_source, sdwan_site, session_id, source_edl, bytes_total, chunks_sent, customer_id, ep_assoc_id, is_exported, is_mptcp_on, is_phishing, is_saas_app, outbound_if, risk_of_app, sequence_no, source_port, source_user, source_uuid, vendor_name, app_category, chunks_total, container_id, is_container, is_decrypted, is_encrypted, is_forwarded, is_offloaded, pa_node_type, packets_sent, rule_matched, tunneled_app, url_category, action_source, dest_location, is_sym_return, is_url_denied, link_switches, log_source_id, nat_dest_port, packets_total, platform_type, pod_namespace, sdwan_cluster, traffic_flags, tunnelid_imsi, config_version, dest_device_os, is_transaction, chunks_received, dest_device_mac, log_source_name, nat_source_port, panorama_serial, sdwan_fec_ratio, session_tracker, source_location, app_sub_category, container_of_app, count_of_repeats, dest_device_host, ha_session_owner, http2_connection, is_prisma_branch, is_prisma_mobile, monitor_tag_imei, pa_sub_tenant_id, packets_received, source_device_os, dest_device_class, dest_device_model, dynusergroup_name, is_captive_portal, is_decrypt_mirror, is_decryption_log, is_packet_capture, is_recon_excluded, is_source_x_fwded, link_change_count, parent_session_id, parent_start_time, rule_matched_uuid, sdwan_device_type, source_device_mac, technology_of_app, dest_device_vendor, sdwan_cluster_type, sess_owner_rt_midx, session_end_reason, session_start_time, source_device_host, total_time_elapsed, dest_device_profile, dest_user_info_name, dest_user_info_uuid, is_client_to_server, is_server_to_client, is_tunnel_inspected, log_source_group_id, source_device_class, source_device_model, dest_device_category, dest_device_osfamily, is_non_std_dest_port, log_source_tz_offset, source_device_vendor, dest_device_osversion, dest_user_info_domain, source_device_profile, source_user_info_name, source_user_info_uuid, endpoint_serial_number, non_standard_dest_port, source_device_category, source_device_osfamily, inbound_if_details_port, inbound_if_details_slot, inbound_if_details_type, inbound_if_details_unit, sanctioned_state_of_app, source_device_osversion, source_user_info_domain, time_generated_high_res, nssai_network_slice_type, outbound_if_details_port, outbound_if_details_slot, outbound_if_details_type, outbound_if_details_unit, dest_dynamic_address_group, is_decrypted_payload_fwded, is_l7_inspection_b4_session, source_dynamic_address_group, nssai_network_slice_differentiator
```

## When to use

NGFW  Query Fields. Queries the `panw_ngfw_traffic_raw` dataset directly. Uses stages: `fields`.

## Variations

_(No variations are documented for this entry.)_
