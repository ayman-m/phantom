# Retrieve File

**HTTP**: `POST /public_api/v1/endpoints/file_retrieval/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xsiam_endpoints_retrieve_file`
**Phantom connector**: `xsiam` (per-instance: see Tools tab on `/connectors/xsiam-<instance>`)

**Official docs**: https://docs.paloaltonetworks.com/cortex/xsiam/xsiam-api/xsiam-apis/response-actions/retrieve-file.html

## Purpose

Retrieve files from selected endpoints. You can retrieve up to 20 files, from no more than 10 endpoints.

## Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `endpoint_id_list` | `List[str]` | `None` | List of endpoint IDs. |
| `files` | `Dict[str, List[str]]` | `None` | dictionary containing the type of platform and list of file paths you want to retrieve. Valid platform type keywords are: ["windows", "linux", "macos"]. |
| `incident_id` | `str` | `None` | When included in the request, the Retrieve File action will appear in the Cortex XSIAM Incident View Timeline tab. |

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

- This endpoint is a `POST` to the XDR `/public_api/v1/endpoints/file_retrieval/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/xsiam-client`'s `retrieve_file` wrapper — see https://github.com/ebarti/xsiam-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xsiam_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/xsiam/src/connector.py` → `xsiam_endpoints_retrieve_file`
- Source mapping: `ebarti/cortex_xdr_client/api/endpoints_api.py` → `retrieve_file`
