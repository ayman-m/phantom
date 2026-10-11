# Get Action Status

**HTTP**: `POST /public_api/v1/actions/get_action_status/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xsiam_response_get_action_status`
**Phantom connector**: `xsiam` (per-instance: see Tools tab on `/connectors/xsiam-<instance>`)

**Official docs**: https://docs.paloaltonetworks.com/cortex/xsiam/xsiam-api/xsiam-apis/response-actions/get-action-status.html

## Purpose

Retrieve the status of the requested actions according to the action ID.

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

- This endpoint is a `POST` to the XDR `/public_api/v1/actions/get_action_status/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/xsiam-client`'s `get_action_status` wrapper — see https://github.com/ebarti/xsiam-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xsiam_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/xsiam/src/connector.py` → `xsiam_response_get_action_status`
- Source mapping: `ebarti/cortex_xdr_client/api/actions_api.py` → `get_action_status`
