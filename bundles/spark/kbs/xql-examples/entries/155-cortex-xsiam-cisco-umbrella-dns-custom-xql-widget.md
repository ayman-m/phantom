---
id: XQL-155-e9fc23f7
title: Cortex XSIAM Cisco Umbrella DNS - Custom XQL Widget
category: investigation
dataset: cisco_umbrella_raw
tags:
  - comp
  - filter
  - limit
  - view
---

# Cortex XSIAM Cisco Umbrella DNS - Custom XQL Widget

**Dataset**: `cisco_umbrella_raw`

```sql
dataset = cisco_umbrella_raw
| filter (action not contains """Allowed""")
| comp count(domain) as domain_count by domain
| limit 50
| view graph type = wordcloud xaxis = domain yaxis = domain_count word_color = "#00ff5b"
```

## When to use

Cortex XSIAM Cisco Umbrella DNS - Custom XQL Widget. Queries the `cisco_umbrella_raw` dataset directly, filtered on `(action not contains """Allowed""")`. Uses stages: `filter`, `comp`, `limit`, `view`.

## Variations

_(No variations are documented for this entry.)_
