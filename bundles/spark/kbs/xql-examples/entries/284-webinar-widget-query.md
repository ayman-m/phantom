---
id: XQL-284-a79852e4
title: Webinar - Widget Query
category: investigation
dataset: snort_labids_raw
tags:
  - datamodel
  - fields
  - filter
  - comp
  - sort
  - view
  - snort_labids_raw
  - source:datamodel
---

# Webinar - Widget Query

**Dataset**: `snort_labids_raw`

```sql
datamodel dataset = snort_labids_raw 
| fields xdm.alert.category, xdm.source.ipv4  
| filter incidr( xdm.source.ipv4, "10.0.0.0/24") =true 
| comp count() as count_source_ip by xdm.source.ipv4 
| sort desc count_source_ip
| view graph type = column subtype = grouped layout = horizontal show_callouts = `true` xaxis = xdm.source.ipv4 yaxis = count_source_ip seriescolor("count_source_ip","#ec7c7c") xaxistitle = "Alerts Count" yaxistitle = "Source IP" seriestitle("count_source_ip","Alerts")
```

## When to use

Webinar - Widget Query. XDM-normalized query over `snort_labids_raw`, filtered on `incidr( xdm.source.ipv4, "10.0.0.0/24") =true`. Uses stages: `datamodel`, `fields`, `filter`, `comp`, `sort`, `view`.

## Variations

_(No variations are documented for this entry.)_
