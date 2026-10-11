# Update Alerts

**HTTP**: `POST /public_api/v1/alerts/update_alerts/`
**MCP tool**: `xsiam_alerts_update`

**Official docs**: https://docs.paloaltonetworks.com/cortex/xsiam/xsiam-api/xsiam-apis/alerts/update-alerts

## Purpose

Bulk-update one or more alerts. Common operations: change severity, set status to resolved, add a comment, reassign. Use after `xsiam_alerts_list` to triage alerts in batches.

## Parameters

| Param | Type | Required | Description |
|---|---|---|---|
| `alert_id_list` | `list[str]` | yes | List of alert IDs to apply the same update to. |
| `update_data` | `dict` | yes | Update fields — see schema below. |

### `update_data` schema

| Field | Type | Description |
|---|---|---|
| `severity` | enum | `"informational" / "low" / "medium" / "high" / "critical"` |
| `status` | enum | `"new" / "under_investigation" / "resolved_true_positive" / "resolved_false_positive" / "resolved_known_issue"` |
| `resolve_comment` | str | Comment associated with the status change. |
| `assigned_user` | str | Email of user to assign. |

## Request body

```json
{
  "request_data": {
    "alert_id_list": ["alert-001", "alert-002"],
    "update_data": {"status": "resolved_false_positive", "resolve_comment": "duplicate of incident 12345"}
  }
}
```

## Returns

```json
{ "ok": true, "updated_count": 2, "alert_id_list": [...] }
```

## Cross-references

- Phantom tool: `bundles/spark/connectors/xsiam/src/connector.py` → `xsiam_alerts_update`
