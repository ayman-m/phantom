# Get Script Execution Status

**HTTP**: `POST /public_api/v1/scripts/get_script_execution_status/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xsiam_scripts_get_execution_status`
**Phantom connector**: `xsiam` (per-instance: see Tools tab on `/connectors/xsiam-<instance>`)

**Official docs**: https://docs.paloaltonetworks.com/cortex/xsiam/xsiam-api/xsiam-apis/script-execution/get-script-execution-status.html

## Purpose

Retrieve the status of a script execution action.

## Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `action_id` | `int` | `—` | Integer, identifier of the action |

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

An object of type GetScriptsExecutionStatus if successful.

## Notes

- This endpoint is a `POST` to the XDR `/public_api/v1/scripts/get_script_execution_status/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/xsiam-client`'s `get_script_execution_status` wrapper — see https://github.com/ebarti/xsiam-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xsiam_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/xsiam/src/connector.py` → `xsiam_scripts_get_execution_status`
- Source mapping: `ebarti/cortex_xdr_client/api/scripts_api.py` → `get_script_execution_status`
