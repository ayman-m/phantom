---
id: XQL-144-d782c07a
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
| alter localip = arraystring(local_ip, ", ")
| alter Room =
if (incidr(localip, "10.220.32.0/24"),"Suite 03",
if (incidr(localip , "10.220.33.0/24"),"Suite 04",
if (incidr(localip , "10.220.34.0/24"),"Suite 07",
if (incidr(localip , "10.220.35.0/24"),"Suite 09",
if (incidr(localip , "10.220.36.0/24"),"Suite 10",
if (incidr(localip , "10.220.37.0/24"),"Suite 12",
if (incidr(localip , "10.220.38.0/24"),"Suite 13",
if (incidr(localip , "10.220.39.0/24"),"Suite 14",
if (incidr(localip , "10.220.40.0/24"),"Suite 15",
if (incidr(localip , "10.220.41.0/24"),"Suite 16",
if (incidr(localip , "10.220.42.0/24"),"Suite 17",
if (incidr(localip , "10.220.43.0/24"),"South Gallery 15",
if (incidr(localip , "10.220.44.0/24"),"South Gallery 19",
if (incidr(localip , "10.220.45.0/24"),"South Gallery 17",
if (incidr(localip , "10.220.46.0/24"),"South Gallery 20",
if (incidr(localip , "10.220.47.0/24"),"South Gallery 22",
if (incidr(localip , "192.168.128.0/18"),"General Wifi",
if (incidr(localip , "10.220.27.0/24"),"Arsenal",
if (incidr(localip , "10.220.251.0/24"),"SOC",
"Other")))))))))))))))))))
| filter Room != "Other"
| comp count(alert_id) as Occurences by Room
| sort desc Occurences
| view graph type = pie subtype = full show_callouts = `true` show_callouts_names = `true` xaxis = Room yaxis = Occurences valuecolor("Suite 17","#e362aa") font = "Arial"
```

## When to use

broken_widgets - Custom XQL Widget. Queries the `alerts` dataset directly, filtered on `Room != "Other"`. Uses stages: `alter`, `filter`, `comp`, `sort`, `view`.

## Variations

_(No variations are documented for this entry.)_
