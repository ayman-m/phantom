---
id: XQL-139-7ec29702
title: Cortex XSIAM JAMF Monitoring - Custom XQL Widget
category: investigation
dataset: jamf_pro_raw
tags:
  - alter
  - comp
  - view
---

# Cortex XSIAM JAMF Monitoring - Custom XQL Widget

**Dataset**: `jamf_pro_raw`

```sql
dataset = jamf_pro_raw
|alter webhookEvent = json_extract_scalar(webhook, "$.webhookEvent")
| comp count(webhookEvent) as webhook_event_type by webhookEvent
| view graph type = pie xaxis = webhookEvent yaxis = webhook_event_type
```

## When to use

Cortex XSIAM JAMF Monitoring - Custom XQL Widget. Queries the `jamf_pro_raw` dataset directly. Uses stages: `alter`, `comp`, `view`.

## Variations

_(No variations are documented for this entry.)_
