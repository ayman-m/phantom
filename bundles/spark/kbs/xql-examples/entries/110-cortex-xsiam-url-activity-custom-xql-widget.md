---
id: XQL-110-4c54581e
title: Cortex XSIAM URL Activity - Custom XQL Widget
category: investigation
dataset: panw_ngfw_url_raw
tags:
  - comp
  - filter
  - sort
  - view
---

# Cortex XSIAM URL Activity - Custom XQL Widget

**Dataset**: `panw_ngfw_url_raw`

```sql
dataset = panw_ngfw_url_raw
| filter to_zone = "internet" and from_zone = "general_wifi" and url_category = "artificial-intelligence"
| filter url_category_list contains "AI-conversational"
| filter app contains "chatgpt" or app contains "openai" or app contains "perplexity" or app contains "deepseek" or app contains "gemini" or app contains "claude"
| comp count(app) as counter by app
| sort desc counter
| view graph type = wordcloud header = "- Popular LLMs" xaxis = app yaxis = counter word_color = "#5ae9d2" headerfontsize = 20
```

## When to use

Cortex XSIAM URL Activity - Custom XQL Widget. Queries the `panw_ngfw_url_raw` dataset directly, filtered on `to_zone = "internet" and from_zone = "general_wifi" and url_category = "artificial-intelligence"`. Uses stages: `filter`, `comp`, `sort`, `view`.

## Variations

_(No variations are documented for this entry.)_
