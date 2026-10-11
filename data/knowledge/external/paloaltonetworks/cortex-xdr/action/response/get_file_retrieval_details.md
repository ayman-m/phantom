# Get File Retrieval Details

**HTTP**: `POST /public_api/v1/actions/file_retrieval_details/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xdr_response_get_file_retrieval_details`
**Phantom connector**: `cortex-xdr` (per-instance: see Tools tab on `/connectors/cortex-xdr-<instance>`)

## Purpose

Retrieve the status of the requested file retrieval action.

## Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `group_action_id` | `int` | `—` | String the represents the Action ID of the selected request. |

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

Returns a GetActionStatus object if successful.

## Notes

- This endpoint is a `POST` to the XDR `/public_api/v1/actions/file_retrieval_details/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/cortex-xdr-client`'s `get_file_retrieval_details` wrapper — see https://github.com/ebarti/cortex-xdr-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xdr_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/cortex-xdr/src/connector.py` → `xdr_response_get_file_retrieval_details`
- Source mapping: `ebarti/cortex_xdr_client/api/actions_api.py` → `get_file_retrieval_details`
