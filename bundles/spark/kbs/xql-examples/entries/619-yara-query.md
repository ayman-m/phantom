---
id: XQL-619-1be40f8f
title: Yara Query
category: investigation
dataset: yara_scans_raw
tags:
  - config
  - fields
  - yara_scans_raw
  - source:dataset
---

# Yara Query

**Dataset**: `yara_scans_raw`

```sql
config timeframe = 1H | dataset = yara_scans_raw | fields active_workers , additional_data , alert_count_last_hour , api_endpoint , avg_processing_time_ms , cache_hit_rate , compilation_success_rate , cpu_percent , current_file , current_rate_files_per_sec , data , dateOfScan , detections_found , disk_io_mb , eff_cpu_efficiency , eff_io_intensity , eff_memory_efficiency , eff_network_intensity , elapsed_seconds , elapsed_time_formatted , elapsed_time_seconds , error_rate_percent , estimated_completion , eta_seconds , failed_rules_count , failed_rules_skipped , file_name , filename , files_processed , files_remaining , files_scanned , files_skipped , hit_rate_percent , hostname , ipAddress , ip_address , ip_addresses , junction_skips , level , log_type , logging_format , match , max_file_mb , max_workers , memory_mb , memory_usage_mb , message , metadata , monitoring_duration_minutes , net_recv_mb , net_sent_mb , net_total_mb , network_mb , offset , os_info , phase , platform , proc_cpu_percent , proc_file_descriptors , proc_io_read_mb , proc_io_write_mb , proc_memory_mb , proc_memory_percent , proc_thread_count , python_version , queue_size , rule , rule_id , rule_source , scan_id , scan_rate_files_per_sec , scan_rate_files_per_second , scan_start_time , scan_status , scan_targets , source , string , sys_cpu_percent , sys_disk_free_gb , sys_disk_total_gb , sys_disk_used_percent , sys_load_avg_15m , sys_load_avg_1m , sys_load_avg_5m , sys_memory_available_mb , sys_memory_total_mb , sys_memory_used_percent , timestamp_iso , total_detections , total_requests , trend_cpu_avg_10min , trend_cpu_trend , trend_data_points , trend_memory_avg_10min , trend_memory_trend , type , unique_real_paths , upload_enabled , upload_timestamp , uploader_version , valid_rules_compiled , valid_rules_count , yara_version
```

## When to use

Yara Query. Queries the `yara_scans_raw` dataset directly. Uses stages: `config`, `fields`.

## Variations

_(No variations are documented for this entry.)_
