---
id: XQL-140-d782c07a
title: broken_widgets - Custom XQL Widget
category: investigation
dataset: incidents
tags:
  - alter
  - comp
  - dataset
  - fields
  - filter
  - join
  - view
---

# broken_widgets - Custom XQL Widget

**Dataset**: `incidents`

```sql
config timeframe = 7D
| dataset = incidents
| fields incident_id, creation_time, description
| filter timestamp_diff(current_time(),creation_time, "DAY") <= 7
| join type=left (config timeframe = 7D
    |dataset = alerts
    | fields alert_arrival_timestamp, incident_id as inc_id, alert_id, resolution_status
    ) as alert_table
    alert_table.inc_id = incident_id
| comp min(alert_id) as first_alert_id, earliest(creation_time) as incident_creation_time by incident_id, resolution_status
| filter first_alert_id != null
| join type = left (config timeframe = 7D
    | dataset = management_auditing
    | fields management_auditing_type, subtype, description, email
    | filter management_auditing_type = ENUM.MANAGEMENT_AUDIT_ISSUE_MANAGEMENT and subtype in ("Update Issue") and description contains "to In Progress"
    | alter alert_id = to_integer(arrayindex(regextract(description,"Changed issue with id ([0-9]+) status to In Progress"),0))
    | fields _time as under_investigation_timestamp_alert, alert_id, email as email_alert) as management_auditing_table
    management_auditing_table.alert_id = first_alert_id
| join type = left (config timeframe = 7D
    |dataset = management_auditing
    | fields management_auditing_type, subtype, description, email
    | filter management_auditing_type = ENUM.MANAGEMENT_AUDIT_CASE_MANAGEMENT and subtype in ("Change Case Status") and description contains "to In Progress"
    | alter inc_id = to_integer(arrayindex(regextract(description,"Changed case ([0-9]+) status to In Progress"),0))
    | fields _time as under_investigation_timestamp_incident, inc_id, email as email_incident) as management_auditing_table
    management_auditing_table.inc_id = incident_id
| fields incident_id, incident_creation_time, first_alert_id, under_investigation_timestamp_alert, under_investigation_timestamp_incident, email_alert, email_incident, resolution_status
| alter under_investigation_timestamp = if(under_investigation_timestamp_alert!=null, under_investigation_timestamp_alert, under_investigation_timestamp_incident),
    email = if(email_alert!=null, email_alert, email_incident)
| filter under_investigation_timestamp_incident != null
| alter MTTA = divide(timestamp_diff(under_investigation_timestamp_incident,incident_creation_time,"MILLISECOND"),60000)//1000 * 60 = 1000 milliseconds and 60 seconds per minute
| alter MTTA = if(MTTA<0,0,MTTA)
| comp avg(MTTA) as MTTA
| alter MTTA = round(MTTA)
| view graph type = gauge subtype = radial header = "MTTA" yaxis = MTTA maxscalerange = 12 scale_threshold("#d7e612") dataunit = "minutes" default_limit = `false` headerfontsize = 30 legendfontsize = 30
```

## When to use

broken_widgets - Custom XQL Widget. XQL pattern, filtered on `timestamp_diff(current_time(),creation_time, "DAY") <= 7`. Uses stages: `dataset`, `fields`, `filter`, `join`, `comp`, `alter`.

## Variations

_(No variations are documented for this entry.)_
