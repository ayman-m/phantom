---
id: XQL-824-3327c5ef
title: Issues by MITRE tactic via XDM (7d) — scalar field
category: investigation
dataset: issues
tags:
  - filter
  - comp
  - sort
  - limit
  - issues
  - xdm
  - mitre
---

# Issues by MITRE tactic via XDM (7d) — scalar field

**Dataset**: `issues`

```sql
config timeframe = 7d
| dataset = issues
| filter xdm.issue.mitre_tactics != null
| comp count() as cnt by xdm.issue.mitre_tactics
| sort desc cnt
| limit 10
```

## When to use

XDM-normalized MITRE tactic distribution. `xdm.issue.mitre_tactics` is a scalar string in this tenant; aggregate directly without arrayexpand.

## Variations

_(No variations are documented for this entry.)_
