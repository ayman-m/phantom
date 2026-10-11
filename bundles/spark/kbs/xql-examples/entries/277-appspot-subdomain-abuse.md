---
id: XQL-277-1e0e1ab8
title: Appspot subdomain abuse
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

# Appspot subdomain abuse

**Dataset**: `email_data`

```sql
dataset = email_data
| arrayexpand urls
| arrayexpand decoded_urls
| arrayexpand recipients
| alter full_domain = regextract(to_string(urls), "^(?:https?://)?([^/?#]+)")
| alter from_address = json_extract(to_json_string(from) , "$.address")
| alter recipient_address = json_extract(to_json_string(recipients) , "$.address")
| filter full_domain != null and full_domain ~= "\b[\w-]+-dot-[\w.-]+\.appspot\.com\b" and (urls contains recipient_address or decoded_urls contains recipient_address)
| fields from_address,urls
```

## When to use

Display potential phishing campaigns associated with Appspot abuse. These emails frequently contain phishing links that utilize the recipients' own email address as a unique identifier in the URI.

## Variations

_(No variations are documented for this entry.)_
