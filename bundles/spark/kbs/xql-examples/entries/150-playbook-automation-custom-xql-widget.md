---
id: XQL-150-0170f0b5
title: Playbook Automation - Custom XQL Widget
category: investigation
dataset: xsiam_playbookmetrics_raw
tags:
  - alter
  - comp
  - dedup
  - view
---

# Playbook Automation - Custom XQL Widget

**Dataset**: `xsiam_playbookmetrics_raw`

```sql
dataset = xsiam_playbookmetrics_raw
| alter playbookId = alert->playbookId
| alter alertId = alert->id
| dedup alertId
| comp count(playbookId)
| view graph type = single subtype = standard header = "Playbook Runs" yaxis = count_1
```

## When to use

Playbook Automation - Custom XQL Widget. Queries the `xsiam_playbookmetrics_raw` dataset directly. Uses stages: `alter`, `dedup`, `comp`, `view`.

## Variations

_(No variations are documented for this entry.)_
