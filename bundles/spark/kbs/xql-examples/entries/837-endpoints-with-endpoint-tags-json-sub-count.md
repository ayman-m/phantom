---
id: XQL-837-34d7abf9
title: Endpoints with endpoint-tags JSON sub-count
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

# Endpoints with endpoint-tags JSON sub-count

**Dataset**: `endpoints`

```sql
dataset = endpoints
| filter tags != null
| alter endpoint_tag_count = array_length(json_extract_array(tags, "$.endpoint_tags"))
| alter server_tag_count = array_length(json_extract_array(tags, "$.server_tags"))
| filter endpoint_tag_count > 0 or server_tag_count > 0
| fields endpoint_name, endpoint_tag_count, server_tag_count
| sort desc endpoint_tag_count
| limit 10
```

## When to use

Endpoint vs server tag counts per host. The `tags` field is JSON with both arrays nested; `json_extract_array` + `array_length` gets the per-subarray count.

## Variations

_(No variations are documented for this entry.)_
