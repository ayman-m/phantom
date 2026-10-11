# Update Incident

**HTTP**: `POST /public_api/v1/incidents/update_incident/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id`)
**MCP tool**: `xdr_incidents_update`
**Phantom connector**: `cortex-xdr`

**Official docs**: https://docs.paloaltonetworks.com/cortex/cortex-xdr/cortex-xdr-api/cortex-xdr-apis/incident-management/update-incident

## Purpose

Update one XDR incident's mutable metadata fields — status, severity, assignee, manual description, resolve comment. Used after `xdr_incidents_list` + `xdr_incidents_get_extra_data` to triage and assign.

## Parameters

| Param | Type | Required | Description |
|---|---|---|---|
| `incident_id` | `str` | yes | Incident ID from `xdr_incidents_list`. |
| `update_data` | `dict` | yes | Fields to update — see schema below. Only present fields are sent. |

### `update_data` schema

| Field | Type | Description |
|---|---|---|
| `assigned_user_mail` | str | Email of the user to assign. |
| `assigned_user_pretty_name` | str | Display name for the assignee. |
| `manual_severity` | enum | `"low" / "medium" / "high" / "critical"` |
| `manual_description` | str | Operator-provided description. |
| `status` | enum | `"new" / "under_investigation" / "resolved_threat_handled" / "resolved_known_issue" / "resolved_duplicate" / "resolved_false_positive" / "resolved_other"` |
| `resolve_comment` | str | Comment shown alongside resolve-status. |

## Request body

```json
{
  "request_data": {
    "incident_id": "12345",
    "update_data": {
      "status": "under_investigation",
      "assigned_user_mail": "soc-analyst@example.com",
      "manual_severity": "high"
    }
  }
}
```

## Returns

```json
{ "ok": true, "incident_id": "12345", "updated": true }
```

## Notes

- The status enum values are exactly as listed — XDR rejects anything else with HTTP 400.
- Operator-facing common workflows:
  - "Resolve incident X as false positive with comment Y" → `{status: "resolved_false_positive", resolve_comment: "Y"}`
  - "Assign to user@example.com and raise to critical" → `{assigned_user_mail: "...", manual_severity: "critical"}`

## Cross-references

- Phantom tool: `bundles/spark/connectors/cortex-xdr/src/connector.py` → `xdr_incidents_update`
