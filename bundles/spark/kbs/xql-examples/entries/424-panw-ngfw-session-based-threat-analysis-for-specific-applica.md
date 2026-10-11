---
id: XQL-424-881c8287
title: PANW NGFW | Session-Based Threat Analysis for Specific Applications
category: investigation
dataset: panw_ngfw_threat_raw
tags:
  - filter
  - comp
  - sort
  - panw_ngfw_threat_raw
  - source:dataset
---

# PANW NGFW | Session-Based Threat Analysis for Specific Applications

**Dataset**: `panw_ngfw_threat_raw`

```sql
dataset = panw_ngfw_threat_raw
| filter app in ($application)
| comp count() as threat_count by session_id, app
| sort desc threat_count
```

## When to use

Analyzes Next-Generation-Firewall (NGFW) threat logs based on specific applications and correlates threats to their sessions

## Variations

_(No variations are documented for this entry.)_
