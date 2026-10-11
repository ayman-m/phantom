---
id: XQL-826-7206a8d8
title: Endpoints by server-tag (JSON-extracted)
category: investigation
dataset: endpoints
tags:
  - filter
  - alter
  - arrayexpand
  - comp
  - sort
  - limit
  - endpoints
  - json_extract
---

# Endpoints by server-tag (JSON-extracted)

**Dataset**: `endpoints`

```sql
dataset = endpoints
| filter tags != null
| alter server_tags = json_extract_array(tags, "$.server_tags")
| filter server_tags != null
| arrayexpand server_tags
| comp count() as cnt by server_tags
| sort desc cnt
| limit 10
```

## When to use

Endpoint server-tag distribution. The `tags` field is a JSON string with `server_tags` + `endpoint_tags` subarrays. Uses `json_extract_array` to pull the nested array.

## Variations

_(No variations are documented for this entry.)_
