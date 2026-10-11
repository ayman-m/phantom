---
id: XQL-219-94efc97d
title: Rarely seen App-IDs
category: investigation
dataset: xdr_data
tags:
  - filter
  - alter
  - fields
  - comp
  - sort
  - xdr_data
  - source:dataset
---

# Rarely seen App-IDs

**Dataset**: `xdr_data`

```sql
// NOTE: this query requires Palo Alto Networks NGFW data with Enhanced Application Logs enabled
 dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.STORY and arraystring(action_app_id_transitions,"-") not in("ip-tcp", "ip-udp","") // Filter for story which includes NGFW data and for cases there the app id is not null or ip,tcp or ip,udp as it means it came from the XDR agents without any actual app-id logic. note the use of arraystring, since the field action_app_id_transitions returns a list, and this function makes it a string with - between the items in the list
 | alter app_id = arraystring(action_app_id_transitions,",") // Creating an app-id field
 | fields app_id, event_id // Selecting the app-id field and the event_id
 | comp count(event_id) as counter by app_id // Counting how many app-ids exist
 | filter counter < 100 // Filtering only for app-ids seen less than 100 times
 | sort desc counter // Sorting in descending order
```

## When to use

Display connections with app idse seen fewer than 100 times across the data

## Variations

_(No variations are documented for this entry.)_
