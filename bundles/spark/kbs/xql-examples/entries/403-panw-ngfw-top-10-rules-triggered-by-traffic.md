---
id: XQL-403-537de8f6
title: PANW NGFW | Top 10 Rules Triggered by Traffic
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - config
  - comp
  - sort
  - limit
  - panw_ngfw_traffic_raw
  - source:dataset
---

# PANW NGFW | Top 10 Rules Triggered by Traffic

**Dataset**: `panw_ngfw_traffic_raw`

```sql
config timeframe = 7d
| dataset = panw_ngfw_traffic_raw
| comp count() as rule_trigger_count by rule_matched
| sort desc rule_trigger_count
| limit 10
```

## When to use

Identifies the top ten Next-Generation-Firewall (NGFW)  firewall rules that were triggered most frequently in the last 7 days

## Variations

_(No variations are documented for this entry.)_
