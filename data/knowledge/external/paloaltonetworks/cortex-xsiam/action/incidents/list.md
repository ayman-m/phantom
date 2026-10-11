# Get Incidents

**HTTP**: `POST /public_api/v1/incidents/get_incidents/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xsiam_incidents_list`
**Phantom connector**: `xsiam` (per-instance: see Tools tab on `/connectors/xsiam-<instance>`)

**Official docs**: https://docs.paloaltonetworks.com/cortex/xsiam/xsiam-api/xsiam-apis/incident-management/get-incidents.html

## Purpose

Get a list of incidents filtered by a list of incident IDs, modification time, or creation time.

## Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `modification_time` | `int` | `None` | Time the incident has been modified. |
| `after_modification` | `bool` | `False` | If the modification date will be the upper or lower bound limit. |
| `creation_time` | `int` | `None` | Incident's creation time. |
| `after_creation` | `bool` | `False` | If the creation date will be the upper or lower bound limit. |
| `incident_id_list` | `List[str]` | `None` | List of incident IDs. |
| `description` | `str` | `None` | Incident description. |
| `description_contains` | `bool` | `False` | If the description will contain the search string. |
| `alert_sources` | `List[str]` | `None` | Source which detected the alert. |
| `status` | `IncidentStatus` | `None` | Represents the status of the incident. |
| `status_equal` | `bool` | `True` | If the status will be equal to the given status. |
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

Returns a GetIncidentsResponse object if successful.

## Notes

- This endpoint is a `POST` to the XDR `/public_api/v1/incidents/get_incidents/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/xsiam-client`'s `get_incidents` wrapper — see https://github.com/ebarti/xsiam-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xsiam_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/xsiam/src/connector.py` → `xsiam_incidents_list`
- Source mapping: `ebarti/cortex_xdr_client/api/incidents_api.py` → `get_incidents`
