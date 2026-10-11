---
id: XQL-044-f19ab529
title: Testing Suricata
category: investigation
dataset: corelight_zeek_raw
tags:
  - comp
  - fields
  - filter
---

# Testing Suricata

**Dataset**: `corelight_zeek_raw`

```sql
dataset = corelight_zeek_raw
| filter _path = "suricata_corelight"
| fields alert_category, id_orig_h , id_resp_h, alert_rule , alert_metadata
//| comp count() as t by id_orig_h addrawdata = true
```

## When to use

Testing Suricata. Queries the `corelight_zeek_raw` dataset directly, filtered on `_path = "suricata_corelight"`. Uses stages: `filter`, `fields`, `comp`.

## Variations

_(No variations are documented for this entry.)_
