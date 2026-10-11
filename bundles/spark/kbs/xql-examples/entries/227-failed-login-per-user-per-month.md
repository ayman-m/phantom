---
id: XQL-227-c20ac553
title: Failed login per User per month
category: investigation
dataset: xdr_data
tags:
  - filter
  - alter
  - fields
  - comp
  - view
  - xdr_data
  - source:dataset
---

# Failed login per User per month

**Dataset**: `xdr_data`

```sql
dataset = xdr_data // Using the xdr dataset
| filter event_type = ENUM.EVENT_LOG and action_evtlog_event_id = 4625 // Filtering by windows event log and id 4625
| alter month = arrayindex(regextract(to_string(_time),"\d+\-(\d+)-\d+.*"),0), username = lowercase(arrayindex(regextract(action_evtlog_message, "Account For Which Logon Failed:\r\n.*\r\n.*Account Name:.*?(\w.*)\r\n"),0)) // Getting the month of the year (return is between 01 and 12) and getting the user name from the eventlog using regextract to get just a part of the full event log message into an array, then using arrayindex to take the first item in the array
| filter username = lowercase($username) // Filtering for just the username in question
| alter month_string = if(month = "01", "January", month = "02", "February", month = "03", "March", month = "04", "April", month = "05", "May", month = "06", "June", month = "07", "July", month = "08", "August", month = "09", "September", month = "10", "October", month = "11", "November", month = "12", "December", month) // Using and if function to also add the month as an full string
| alter month = concat(month," / ", month_string ) // Concatinating to make one month like 07 / July as it will make it easier to sort
| fields _time, username , month_string, month, event_id // Selecting just the fields needed
| comp count(event_id) as counter by username, month // Counting how many failed logins happened per user per month
| view graph type = column subtype = grouped,horizontal header = "Failed Login Over Time" show_callouts = true xaxis = month yaxis = counter seriescolor("counter","#12a44a") headcolor = "#dedede" gridcolor = "#c6d5e8" font = "Tahoma" headerfontsize = 20 legendfontsize = 15 xvaluesfontsize = 15 yvaluesfontsize = 15 calloutfontsize = 15 legend = false xaxistitle = "Count of failed logins" yaxistitle = "Month" seriestitle("counter","Count of failed logins") // Creating a chart of the results
```

## When to use

Compare failed login events for a given user over the months chosen in the query. Make sure to run on more than one month of data.

## Variations

_(No variations are documented for this entry.)_
