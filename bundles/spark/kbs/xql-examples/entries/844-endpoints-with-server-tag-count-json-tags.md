---
id: XQL-844-380f20b9
title: Endpoints with server-tag count (JSON tags)
category: investigation
dataset: endpoints
tags:
  - filter
  - alter
  - fields
  - sort
  - limit
  - endpoints
  - json_extract_array
  - array_length
---

# Endpoints with server-tag count (JSON tags)

**Dataset**: `endpoints`

```sql
dataset = endpoints
| filter tags != null
| alter server_tags = json_extract_array(tags, "$.server_tags")
| alter tag_count = array_length(server_tags)
| filter tag_count > 0
| fields endpoint_name, server_tags, tag_count
| sort desc tag_count
| limit 10
```

## When to use

Per-endpoint server-tag inventory. Uses `json_extract_array` to pull the nested array, then `array_length` to count tags per endpoint.

## Variations

_(No variations are documented for this entry.)_
