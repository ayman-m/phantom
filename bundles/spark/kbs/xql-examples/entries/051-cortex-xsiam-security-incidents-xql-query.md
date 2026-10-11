---
id: XQL-051-a75720b7
title: Cortex XSIAM Security Incidents - XQL Query
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - comp
  - fields
  - filter
  - limit
  - sort
---

# Cortex XSIAM Security Incidents - XQL Query

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| filter app contains "dns" and threat_category contains "dns-malware" or threat_category contains "dns-phishing"
| filter threat_id != 93031
| fields threat_category, threat_name, url*, sub_type
| comp count(threat_name) as hits, values(threat_category) as dns_type by threat_name
| sort desc hits
| limit 10
```

## When to use

Cortex XSIAM Security Incidents - XQL Query. Queries the `panw_ngfw_threat_raw` dataset directly, filtered on `app contains "dns" and threat_category contains "dns-malware" or threat_category contains "dns-phishing"`. Uses stages: `filter`, `fields`, `comp`, `sort`, `limit`.

## Variations

_(No variations are documented for this entry.)_
