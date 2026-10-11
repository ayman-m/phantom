# Get Incident Extra Data

**HTTP**: `POST /public_api/v1/incidents/get_incident_extra_data/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xsiam_incidents_get_extra_data`
**Phantom connector**: `xsiam` (per-instance: see Tools tab on `/connectors/xsiam-<instance>`)

**Official docs**: https://docs.paloaltonetworks.com/cortex/xsiam/xsiam-api/xsiam-apis/incident-management/get-extra-incident-data.html

## Purpose

Get extra data fields of a specific incident including alerts and key artifacts.

## Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `incident_id` | `str` | `—` | The ID of the incident for which you want to retrieve extra data. |
| `alerts_limit` | `int` | `1000` | Maximum number of related alerts in the incident that you want to retrieve (default 1000). |

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

Returns a GetExtraIncidentDataResponse object if successful.

## Notes

- This endpoint is a `POST` to the XDR `/public_api/v1/incidents/get_incident_extra_data/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/xsiam-client`'s `get_incident_extra_data` wrapper — see https://github.com/ebarti/xsiam-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xsiam_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/xsiam/src/connector.py` → `xsiam_incidents_get_extra_data`
- Source mapping: `ebarti/cortex_xdr_client/api/incidents_api.py` → `get_incident_extra_data`
