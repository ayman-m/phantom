---
id: XQL-415-2c0ac875
title: PANW NGFW | Most Common Threat Actions
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - comp
  - sort
  - panw_ngfw_threat_raw
  - source:dataset
---

# PANW NGFW | Most Common Threat Actions

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| comp count() as action_count by action
| sort desc action_count
```

## When to use

Lists the most common actions taken by the Next-Generation-Firewall (NGFW) in response to detected threats, such as allowing, blocking, or alerting on traffic

## Variations

_(No variations are documented for this entry.)_
