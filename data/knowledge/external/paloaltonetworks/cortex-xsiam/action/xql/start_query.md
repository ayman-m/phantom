# Start Xql Query

**HTTP**: `POST /public_api/v1/xql/start_xql_query/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xsiam_xql_start_query`
**Phantom connector**: `xsiam` (per-instance: see Tools tab on `/connectors/xsiam-<instance>`)

**Official docs**: https://docs.paloaltonetworks.com/cortex/xsiam/xsiam-api/xsiam-apis/xql-apis/start-xql-query.html

## Purpose

Starts an XQL Query.

## Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `query` | `str` | `—` | String of the XQL query. |
| `time_period` | `int` | `None` | Relative Unix timestamp representing the last X hours. |
| `from_date` | `int` | `None` | Absolute Unix timestamp representing a date |
| `to_date` | `int` | `None` | Absolute Unix timestamp representing a date |
| `tenants` | `List[str]` | `None` | List of strings used for running APIs on local and Managed Security tenants. |
| `params` | `dict` | `{}` | Dictionary of parameters to be passed to the request data |

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

String representing the unique ID generate by the response to Start XQL Query API.

## Notes

- This endpoint is a `POST` to the XDR `/public_api/v1/xql/start_xql_query/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/xsiam-client`'s `start_xql_query` wrapper — see https://github.com/ebarti/xsiam-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xsiam_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/xsiam/src/connector.py` → `xsiam_xql_start_query`
- Source mapping: `ebarti/cortex_xdr_client/api/xql_api.py` → `start_xql_query`
