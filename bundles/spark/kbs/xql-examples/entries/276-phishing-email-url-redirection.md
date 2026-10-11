---
id: XQL-276-b4c58603
title: Phishing email URL redirection
category: investigation
dataset: email_data
tags:
  - arrayexpand
  - alter
  - filter
  - fields
  - email_data
  - source:dataset
---

# Phishing email URL redirection

**Dataset**: `email_data`

```sql
dataset = email_data
| arrayexpand urls
| alter from_address = json_extract(to_json_string(from) , "$.address")
| filter urls ~= "s?://(?:www\.)?t\.(?:[\w\-\.]+/+)+(r|redirect)/?"
| fields from_address, urls
```

## When to use

Attackers use URL redirection to manipulate users into visiting a malicious website or to evade detection. This query displays emails associated with a campaign that has used open redirector URLs.

## Variations

_(No variations are documented for this entry.)_
