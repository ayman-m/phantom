# Get Script Metadata

**HTTP**: `POST /public_api/v1/scripts/get_script_metadata/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xsiam_scripts_get_metadata`
**Phantom connector**: `xsiam` (per-instance: see Tools tab on `/connectors/xsiam-<instance>`)

**Official docs**: https://docs.paloaltonetworks.com/cortex/xsiam/xsiam-api/xsiam-apis/script-execution/get-script-metadata.html

## Purpose

Get the full definitions of a specific script in the scripts library.

## Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `script_uid` | `str` | `—` | Unique identifier of the script, returned by the Get Scripts API per script. |

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

An object of type GetScriptMetadataResponse if successful.

## Notes

- This endpoint is a `POST` to the XDR `/public_api/v1/scripts/get_script_metadata/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/xsiam-client`'s `get_script_metadata` wrapper — see https://github.com/ebarti/xsiam-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xsiam_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/xsiam/src/connector.py` → `xsiam_scripts_get_metadata`
- Source mapping: `ebarti/cortex_xdr_client/api/scripts_api.py` → `get_script_metadata`
