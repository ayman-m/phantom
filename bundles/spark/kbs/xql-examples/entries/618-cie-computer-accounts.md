---
id: XQL-618-3736f3ad
title: CIE Computer Accounts
category: investigation
dataset: pan_dss_raw
tags:
  - filter
  - fields
  - pan_dss_raw
  - source:dataset
---

# CIE Computer Accounts

**Dataset**: `pan_dss_raw`

```sql
dataset = pan_dss_raw | filter type = "computer" | fields agent_id , display_name , dn , dns_host_name , domain_name , guid , last_logon_timestamp , last_modified_dc_record , location , member_of , name , netbios , netbios_and_sam_account_name , on_prem_dn_cn , on_prem_dn_domain , on_prem_dn_ou , on_prem_dn_raw , on_prem_extension_attributes , on_prem_last_sync , on_prem_sam_account_name , on_prem_sid , on_prem_sync_enabled , os , os_sp , os_ver , ou , primary_group_id , record_generated_time  , sam_account_name , security_groups , service_principal_names , sid , sid_history , sign_in_sessions_valid_from , source , trust_type , type , user_account_control
```

## When to use

CIE Computer Accounts. Queries the `pan_dss_raw` dataset directly, filtered on `type = "computer"`. Uses stages: `filter`, `fields`.

## Variations

_(No variations are documented for this entry.)_
