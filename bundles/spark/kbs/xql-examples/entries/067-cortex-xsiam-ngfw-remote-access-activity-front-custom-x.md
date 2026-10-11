---
id: XQL-067-47e963ed
title: 'Cortex XSIAM NGFW Remote Access Activity [Front] - Custom XQL Widget'
category: investigation
dataset: panw_ngfw_traffic_raw
tags:
  - alter
  - comp
  - fields
  - filter
  - limit
  - sort
  - view
---

# Cortex XSIAM NGFW Remote Access Activity [Front] - Custom XQL Widget

**Dataset**: `panw_ngfw_traffic_raw`

```sql
dataset = panw_ngfw_traffic_raw
//Filter for remote access applications
| filter url_category = "proxy-avoidance-and-anonymizers" and (app not in("""ssl""", """web-browsing""", """incomplete"""))
//Count total events by app, zone, ip and port
| alter Zone_Direction = concat(to_string(from_zone), " to ", to_string(to_zone))
| comp values(source_ip) as source_ips, values(dest_ip) as dest_ips, sum(bytes_received) as total_bytes_in, sum(bytes_sent) as total_bytes_out, sum(bytes_total) as total_bytes, count(_id) as total_sessions by app, action, zone_direction
| alter TotalGB_sent = divide(total_bytes_out ,1048576), TotalGB_recieved = divide(total_bytes_in, 1048576), TotalGB = divide(total_bytes, 1048576)
| alter Sent_TotalGB = round(TotalGB_sent)
| alter Received_TotalGB = round(TotalGB_recieved)
| alter Total_GB = round(TotalGB)
| fields app, action, Zone_Direction, source_ips, dest_ips, total_sessions , Sent_TotalGB , Received_TotalGB , Total_GB
| sort desc Total_GB
| fields app, total_sessions
| comp count() as counter by app
| sort desc counter
| limit 5
| view graph type = column subtype = grouped layout = horizontal xaxis = app yaxis = counter
```

## When to use

Cortex XSIAM NGFW Remote Access Activity [Front] - Custom XQL Widget. Queries the `panw_ngfw_traffic_raw` dataset directly, filtered on `url_category = "proxy-avoidance-and-anonymizers" and (app not in("""ssl""", """web-browsing""", """incomplete"""))`. Uses stages: `filter`, `alter`, `comp`, `fields`, `sort`, `limit`.

## Variations

_(No variations are documented for this entry.)_
