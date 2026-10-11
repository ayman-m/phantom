---
id: XQL-482-943e6039
title: Office 365 | Unread Emails with Attachments Older Than 48 Hours in the Last 60 days
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

# Office 365 | Unread Emails with Attachments Older Than 48 Hours in the Last 60 days

**Dataset**: `msft_o365_emails_raw`

```sql
config timeframe = 7d
| dataset = msft_o365_emails_raw
| alter email_create_time = createdDateTime
| alter currenttime = current_time()
| alter time_diff_in_hours = timestamp_diff (currenttime, email_create_time, "HOUR")
| filter hasAttachments = true and isRead = false and time_diff_in_hours > 48
| fields email_create_time, currenttime, time_diff_in_hours, *
```

## When to use

Lists the unread emails with attachments in Microsoft O365 that are older than 48 hours in the last 7 days

## Variations

_(No variations are documented for this entry.)_
