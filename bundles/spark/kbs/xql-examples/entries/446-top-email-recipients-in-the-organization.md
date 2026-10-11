---
id: XQL-446-0c80c2d1
title: Top Email Recipients in the Organization
category: investigation
dataset: email_data
tags:
  - alter
  - arrayexpand
  - email_data
  - source:dataset
---

# Top Email Recipients in the Organization

**Dataset**: `email_data`

```sql
dataset = email_data
| alter sender_address = sender -> address
| alter recipients_address = arraymap(recipients , json_extract_scalar("@element","$.address"))
| arrayexpand recipients_address
| top recipients_address
```

## When to use

LIsts the top email recipients in the organizaiton

## Variations

_(No variations are documented for this entry.)_
