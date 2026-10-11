---
id: XQL-193-242f83d0
title: Top 10 Users failing to log in
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - alter
  - comp
  - sort
  - limit
  - view
  - xdr_data
  - source:dataset
---

# Top 10 Users failing to log in

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.EVENT_LOG and action_evtlog_event_id = 4625 // Filtering by windows event log and id 4625
 | fields action_evtlog_message, event_id // Selecting the full event log message and the event id
 | alter User_Name = lowercase(arrayindex(regextract(action_evtlog_message, "Account For Which Logon Failed:\r\n.*\r\n.*Account Name:.*?(\w.*)\r\n"),0)) // Using regextract to get just the user name into an array, then using arrayindex to take the first item in the array. Also makign sure the resuls are in lower case
 | filter User_Name not contains "*$" // removing computer accounts that end with $. Note that the * is needed too.
 | comp count(event_id) as Counter by User_Name // Counting how many times each user failed to login
 | sort desc Counter // Sorting by the counter
 | limit 10 // Limiting the results to only the top 10
 | view graph type = column subtype = grouped,horizontal show_callouts = true xaxis = user_name yaxis = Counter // Showing results in a bar chart
```

## When to use

Display the top 10 users by the number of times they failed to log in

## Variations

_(No variations are documented for this entry.)_
