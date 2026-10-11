---
id: XQL-435-2d6bbd6f
title: Office 365 | Emails Associated with Alerts 
category: investigation
dataset: msft_graph_security_alerts_raw
tags:
  - filter
  - alter
  - join
  - msft_graph_security_alerts_raw
  - source:dataset
---

# Office 365 | Emails Associated with Alerts 

**Dataset**: `msft_graph_security_alerts_raw`

```sql
dataset = msft_graph_security_alerts_raw
| filter detectionSource = "microsoftDefenderForOffice365"
| alter analyzedMessageEvidence = arrayindex(arrayfilter(evidence ->[] , "@element" -> ["@odata.type"] = "#microsoft.graph.security.analyzedMessageEvidence"), 0)
| alter internetMessageId = analyzedMessageEvidence -> internetMessageId
| join (dataset = email_data ) as emails emails.internet_message_id contains internetMessageId
```

## When to use

Lists the mail events that triggered a Microsoft Defender for Office 365 alert.

## Variations

_(No variations are documented for this entry.)_
