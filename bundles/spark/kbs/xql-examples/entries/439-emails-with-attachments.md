---
id: XQL-439-5db53ac5
title: Emails with Attachments
category: investigation
dataset: email_data
tags:
  - filter
  - fields
  - email_data
  - source:dataset
---

# Emails with Attachments

**Dataset**: `email_data`

```sql
dataset = email_data
| filter has_attachments = true
| fields attachments , has_attachments , sender , recipients , from , *
```

## When to use

Lists emails including attachments

## Variations

_(No variations are documented for this entry.)_
