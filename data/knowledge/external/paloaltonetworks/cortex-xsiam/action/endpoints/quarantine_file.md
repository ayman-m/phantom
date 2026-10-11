# Quarantine File

**HTTP**: `POST /public_api/v1/endpoints/quarantine/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xsiam_endpoints_quarantine_file`
**Phantom connector**: `xsiam` (per-instance: see Tools tab on `/connectors/xsiam-<instance>`)

**Official docs**: https://docs.paloaltonetworks.com/cortex/xsiam/xsiam-api/xsiam-apis/response-actions/quarantine-files.html

## Purpose

Quarantine file on selected endpoints. You can select up to 1000 endpoints.

## Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `endpoint_id_list` | `List[str]` | `None` | List of endpoint IDs. |
| `file_path` | `str` | `None` | String that represents the path of the file you want to quarantine. You must enter a proper path and not symbolic links. |
| `file_hash` | `str` | `None` | String that represents the file’s hash. Hash must be a valid SHA256. |
| `incident_id` | `str` | `None` | When included in the request, the Quarantine File action will appear in the Cortex XSIAM Incident View Timeline tab. |

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

A ResponseActionResponse object if successful.

## Notes

- This endpoint is a `POST` to the XDR `/public_api/v1/endpoints/quarantine/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/xsiam-client`'s `quarantine_file` wrapper — see https://github.com/ebarti/xsiam-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xsiam_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/xsiam/src/connector.py` → `xsiam_endpoints_quarantine_file`
- Source mapping: `ebarti/cortex_xdr_client/api/endpoints_api.py` → `quarantine_file`
