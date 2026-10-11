---
id: XQL-188-ea423b38
title: Rare Process + User Agent
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - alter
  - comp
  - sort
  - xdr_data
  - source:dataset
---

# Rare Process + User Agent

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.NETWORK and event_sub_type = ENUM.NETWORK_HTTP_HEADER // Filtering by network event types and sub type of http header
 | fields actor_process_image_path as Process_Path, action_network_http, event_id // Getting the process which made the connection, the http header, and the event id
 | alter User_Agent=json_extract(action_network_http, "$.headers.User-Agent") // Using json extract to get the user-agent out of the header
 | comp count(event_id) as Counter by Process_Path, User_Agent // Counting how many times a process/user-agent pair was used
 | filter counter < 10 // Filtering for pairs seen less than 10 times
 | sort desc Counter // Sorting by occurrences in a descending order
```

## When to use

Display process + user agent pairs seen fewer than 10 times in a given timeframe

## Variations

_(No variations are documented for this entry.)_
