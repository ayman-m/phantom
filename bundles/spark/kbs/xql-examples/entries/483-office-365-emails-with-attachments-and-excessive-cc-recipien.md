---
id: XQL-483-fcab8668
title: Office 365 | Emails with Attachments and Excessive CC Recipients in the Last 30 Days
category: investigation
dataset: msft_o365_emails_raw
tags:
  - config
  - alter
  - filter
  - fields
  - msft_o365_emails_raw
  - source:dataset
---

# Office 365 | Emails with Attachments and Excessive CC Recipients in the Last 30 Days

**Dataset**: `msft_o365_emails_raw`

```sql
config timeframe = 30d
| dataset = msft_o365_emails_raw
| alter sender_mail = json_extract(sender, "$.emailAddress.address")
| alter sender_domain = regextract(sender_mail, "@([^\"]+)")
| alter cc = ccRecipients -> []
| alter cc_recipients_len = array_length(cc)
| filter hasAttachments = true and cc_recipients_len > 5 and sender_domain not contains "@paloaltonetworks"
| fields sender, sender_domain, ccRecipients, cc, cc_recipients_len, *
```

## When to use

Lists the emails with attachments in Microsoft O365 that were sent to more than 5 CC recipients, excluding the PANW domain, in the last 30 days

## Variations

_(No variations are documented for this entry.)_
