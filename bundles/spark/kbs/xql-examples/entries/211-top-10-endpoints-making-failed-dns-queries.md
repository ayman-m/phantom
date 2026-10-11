---
id: XQL-211-4b716513
title: Top 10 endpoints making failed DNS queries
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - comp
  - sort
  - limit
  - view
  - xdr_data
  - source:dataset
---

# Top 10 endpoints making failed DNS queries

**Dataset**: `xdr_data`

```sql
// NOTE: this query requires Palo Alto Networks NGFW data with Enhanced Application Logs enabled
 dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.STORY and dns_reply_code contains "Non-Existent Domain" // Looking for DNS queries that return an 'non existent domain' response
 | fields event_id, action_local_ip as source_ip // Getting the event id and source IP
 | comp count(event_id) as Counter by source_ip // Counting the number of events per IP
 | sort desc Counter // Sorting in descending order by the amount of failed queries
 | limit 10 // Showing only the top 10 results
 | view graph type = pie show_callouts = true xaxis = source_ip yaxis = Counter // Showing results in a pie chart
```

## When to use

Display top 10 endpoints failing to resolve DNS queries

## Variations

_(No variations are documented for this entry.)_
