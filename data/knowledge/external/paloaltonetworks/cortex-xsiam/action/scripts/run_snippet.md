# Run Snippet Code Script

**HTTP**: `POST /public_api/v1/scripts/run_snippet_code_script/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xsiam_scripts_run_snippet`
**Phantom connector**: `xsiam` (per-instance: see Tools tab on `/connectors/xsiam-<instance>`)

**Official docs**: https://docs.paloaltonetworks.com/cortex/xsiam/xsiam-api/xsiam-apis/script-execution/run-snippet-code-script.html

## Purpose

Initiate a new endpoint script execution action using a snippet code.

## Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `snippet_code` | `str` | `—` | String, contains the snippet code to be executed. |
| `endpoint_id_list` | `List[str]` | `—` | List of endpoint IDs. |
| `timeout` | `int` | `600` | Integer, represents the timeout in seconds for this execution. Default value is 600. |
| `incident_id` | `str` | `None` | String representing the incident ID. When included in the request, the Run Script action will appear in the Cortex XSIAM Incident View Timeline tab. |

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

A dict containing action_id and endpoints_count.

## Notes

- This endpoint is a `POST` to the XDR `/public_api/v1/scripts/run_snippet_code_script/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/xsiam-client`'s `run_snippet_code_script` wrapper — see https://github.com/ebarti/xsiam-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xsiam_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/xsiam/src/connector.py` → `xsiam_scripts_run_snippet`
- Source mapping: `ebarti/cortex_xdr_client/api/scripts_api.py` → `run_snippet_code_script`
