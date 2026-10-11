# Get Script Execution Results

**HTTP**: `POST /public_api/v1/scripts/get_script_execution_results/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xdr_scripts_get_execution_results`
**Phantom connector**: `cortex-xdr` (per-instance: see Tools tab on `/connectors/cortex-xdr-<instance>`)

**Official docs**: https://docs.paloaltonetworks.com/cortex/cortex-xdr/cortex-xdr-api/cortex-xdr-apis/script-execution/get-script-execution-results.html

## Purpose

Retrieve the results of a script execution action.

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

The results of a script execution action.

## Notes

- This endpoint is a `POST` to the XDR `/public_api/v1/scripts/get_script_execution_results/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/cortex-xdr-client`'s `get_script_execution_results` wrapper — see https://github.com/ebarti/cortex-xdr-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xdr_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/cortex-xdr/src/connector.py` → `xdr_scripts_get_execution_results`
- Source mapping: `ebarti/cortex_xdr_client/api/scripts_api.py` → `get_script_execution_results`
