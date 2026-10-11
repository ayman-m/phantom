# Get Alerts

**HTTP**: `POST /public_api/v1/alerts/get_alerts_multi_events/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xsiam_alerts_list`
**Phantom connector**: `xsiam` (per-instance: see Tools tab on `/connectors/xsiam-<instance>`)

**Official docs**: https://docs.paloaltonetworks.com/cortex/xsiam/xsiam-api/xsiam-apis/incident-management/get-alerts.html

## Purpose

Get a list of alerts with multiple events.

## Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `alert_id_list` | `List[int]` | `None` | List of integers of the Alert ID |
| `alert_source_list` | `List[str]` | `None` | List of strings of the Alert source |
| `severities` | `List[AlertSeverity]` | `None` | List of strings of the Alert severity |
| `creation_time` | `int` | `None` | Timestamp of the Creation time. Also known as detection_timestamp. |
| `after_creation` | `bool` | `False` | If the creation date will be the upper or lower bound limit. |
| `server_creation_time` | `int` | `None` | Timestamp of the Server creation time. Also known as local_insert_ts. |
| `after_server_creation` | `bool` | `False` | If the server creation date will be the upper or lower bound limit. |
| `search_from` | `int` | `None` | Integer representing the starting offset within the query result set from which you want incidents returned. |
| `search_to` | `int` | `None` | Integer representing the end offset within the result set after which you do not want incidents returned. |

## Request body (representative)

```json
{
  "request_data": {
    "filters": [ /* see ebarti filter helpers */ ],
    "search_from": 0,
    "search_to": 100
  }
}
```

## Returns

Returns a GetAlertsResponse object if successful.

## Notes

- This endpoint is a `POST` to the XDR `/public_api/v1/alerts/get_alerts_multi_events/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/xsiam-client`'s `get_alerts` wrapper — see https://github.com/ebarti/xsiam-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xsiam_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/xsiam/src/connector.py` → `xsiam_alerts_list`
- Source mapping: `ebarti/cortex_xdr_client/api/alerts_api.py` → `get_alerts`
