---
id: XQL-048-e758f3ac
title: Cortex XSIAM Security Incidents - Custom XQL Widget
category: investigation
dataset: incidents
tags:
  - alter
  - comp
  - fields
  - filter
  - join
  - sort
  - view
---

# Cortex XSIAM Security Incidents - Custom XQL Widget

**Dataset**: `incidents`

```sql
dataset = incidents
| filter starred = 1
| fields _time as modified_time, creation_time, resolved_ts, assigned_user, incident_id, status, assigned_user, description, resolve_comment, severity, starring_ts, first_assignment_ts
| filter status = ENUM.RESOLVED_TRUE_POSITIVE or status = ENUM.RESOLVED_SECURITY_TESTING or status = ENUM.RESOLVED_OTHER  or status = ENUM.RESOLVED_FALSE_POSITIVE or status = ENUM.RESOLVED_KNOWN_ISSUE or status = ENUM.RESOLVED_HANDLED_THREAT or status contains "BH_POSITIVE"
// THE JOINING OF THE ALERT TABLE
| join conflict_strategy = left  type = left
(dataset = alerts
//| filter starred = TRUE
| fields _time as alert_time, event_timestamp, incident_id, alert_id, alert_source, alert_name, alert_type,
        description, user_name, resolution_status, resolution_comment,
        host_name, host_os, action, severity, rule_id, module
        | alter user_name = arrayindex(arraydistinct(user_name), 0)
        | comp values(user_name) as affected_users, values(alert_id) as alert_id, values(alert_name) as alert_name, values(alert_time) as alert_time, values(severity) as alert_severity, values(alert_source) as               alert_type, values(host_os) as host_os by incident_id
        ) as alert_table alert_table.incident_id = incident_id
//FORMAT TIME
| alter first_alert_time = arrayindex(alert_time, 0)
| alter first_alert_timestamp = format_timestamp("%Y-%m-%d %H:%M:%S", arrayindex(alert_time, 0))
| alter modified_timestamp = format_timestamp("%Y-%m-%d %H:%M:%S", modified_time)
| alter resolved_timestamp = format_timestamp("%Y-%m-%d %H:%M:%S", resolved_ts)
| alter creation_timestamp = format_timestamp("%Y-%m-%d %H:%M:%S", creation_time)
| alter starring_timestamp = format_timestamp("%Y-%m-%d %H:%M:%S", starring_ts)
| alter assignment_timestamp = format_timestamp("%Y-%m-%d %H:%M:%S", first_assignment_ts)
//TIME DIFFERENCE
| alter time_to_resolve = timestamp_diff(resolved_ts, creation_time, "MINUTE")
| alter time_to_detect = timestamp_diff(creation_time, first_alert_time, "MINUTE")
| alter time_to_detect =
    if(to_integer(time_to_detect) < 0, 0, time_to_detect)
| alter close_code = status
| alter close_code = replace(close_code, "STATUS_070_RESOLVED_OTHER", "Benign")
| alter close_code = replace(close_code, "STATUS_040_RESOLVED_KNOWN_ISSUE", "No Operation (NOP)")
| alter close_code = replace(close_code, "STATUS_060_RESOLVED_FALSE_POSITIVE", "False Positive")
| alter close_code = replace(close_code, "STATUS_090_TRUE_POSITIVE", "True Positive")
| alter close_code = replace(close_code, "STATUS_100_SECURITY_TESTING", "Bad Practice")
| alter close_code = replace(close_code, "STATUS_RESOLVED_BH_POSITIVE", "Postive")
| fields incident_id, status, assigned_user, description, resolve_comment, close_code, time_to_detect, time_to_resolve, creation_timestamp, resolved_timestamp, starring_timestamp,  assignment_timestamp, modified_timestamp, first_alert_timestamp, affected_users, alert_id, alert_name, alert_severity, alert_type, host_os, severity
| comp count(incident_id) as starred_incident_count by close_code
| sort desc starred_incident_count
| view graph type = line show_callouts = `true` show_callouts_names = `true` xaxis = close_code yaxis = starred_incident_count seriescolor("starred_incident_count","#479ca2") xvaluesfontsize = 0
```

## When to use

Cortex XSIAM Security Incidents - Custom XQL Widget. Queries the `incidents` dataset directly, filtered on `starred = 1`. Uses stages: `filter`, `fields`, `join`, `alter`, `comp`, `sort`.

## Variations

_(No variations are documented for this entry.)_
