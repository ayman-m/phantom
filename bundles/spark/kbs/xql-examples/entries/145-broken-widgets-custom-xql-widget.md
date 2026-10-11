---
id: XQL-145-d782c07a
title: broken_widgets - Custom XQL Widget
category: investigation
dataset: alerts
tags:
  - alter
  - comp
  - filter
  - sort
  - view
---

# broken_widgets - Custom XQL Widget

**Dataset**: `alerts`

```sql
dataset = alerts
| filter category != "IP"
| filter category != "Domain Name"
| alter Room =
if (incidr(endpoint_id , "192.168.120.0/24"),"Suite 03",
if (incidr(endpoint_id , "192.168.121.0/24"),"Suite 04",
if (incidr(endpoint_id , "192.168.122.0/24"),"Suite 07",
if (incidr(endpoint_id , "192.168.123.0/24"),"Suite 09",
if (incidr(endpoint_id , "192.168.124.0/24"),"Suite 10",
if (incidr(endpoint_id , "192.168.125.0/24"),"Suite 12",
if (incidr(endpoint_id , "192.168.126.0/24"),"Suite 13",
if (incidr(endpoint_id , "192.168.127.0/24"),"Suite 14",
if (incidr(endpoint_id , "192.168.128.0/24"),"Suite 15",
if (incidr(endpoint_id , "192.168.129.0/24"),"Suite 16",
if (incidr(endpoint_id , "192.168.130.0/24"),"Suite 17",
if (incidr(endpoint_id , "192.168.131.0/24"),"Suite 14",
if (incidr(endpoint_id , "192.168.132.0/24"),"Suite 15",
if (incidr(endpoint_id , "192.168.133.0/24"),"Suite 16",
if (incidr(endpoint_id , "192.168.240.0/24"),"General Wifi",
if (incidr(endpoint_id , "192.168.101.0/24"),"Sales Suite",
if (incidr(endpoint_id , "192.168.197.0/24"),"Arsenal",
if (incidr(endpoint_id , "192.168.131.0/24"),"PSuite02",
if (incidr(endpoint_id , "192.168.132.0/24"),"PSuite03",
"Other")))))))))))))))))))
| comp count(alert_id) as Occurences by Room
| sort desc Occurences
|
 view graph type = pie subtype = full show_callouts = `true` show_callouts_names = `true` xaxis = Room yaxis = Occurences valuecolor("Suite 17","#e362aa") font = "Arial"
```

## When to use

broken_widgets - Custom XQL Widget. Queries the `alerts` dataset directly, filtered on `category != "IP"`. Uses stages: `filter`, `alter`, `comp`, `sort`, `view`.

## Variations

_(No variations are documented for this entry.)_
