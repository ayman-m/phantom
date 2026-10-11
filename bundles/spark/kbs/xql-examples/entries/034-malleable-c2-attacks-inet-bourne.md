---
id: XQL-034-4440ea09
title: Malleable C2 Attacks Inet Bourne
category: general
dataset: panw_ngfw_threat_raw
tags:
  - filter
---

# Malleable C2 Attacks Inet Bourne

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| filter (threat_id = 9950 or threat_id = 89951 or threat_id = 89952 or threat_id = 89953 or threat_id = 89954 or threat_id = 89955 or threat_id = 89956 or threat_id = 89957 or threat_id = 89958 or threat_id = 99951 or threat_id = 99950 )  and ( from_zone  = "Internet" or to_zone  = "Internet")
```

## When to use

Malleable C2 Attacks Inet Bourne. Queries the `panw_ngfw_threat_raw` dataset directly, filtered on `(threat_id = 9950 or threat_id = 89951 or threat_id = 89952 or threat_id = 89953 or threat_id = 89954 or threat_id = 89955 or threat_id = 89`. Uses stages: `filter`.

## Variations

_(No variations are documented for this entry.)_
