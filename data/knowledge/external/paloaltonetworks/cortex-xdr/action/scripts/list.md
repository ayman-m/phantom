# Get Scripts

**HTTP**: `POST /public_api/v1/scripts/get_scripts/`
**Auth**: Bearer (`Authorization` + `x-xdr-auth-id` + `x-xdr-nonce` + `x-xdr-timestamp` when advanced)
**MCP tool**: `xdr_scripts_list`
**Phantom connector**: `cortex-xdr` (per-instance: see Tools tab on `/connectors/cortex-xdr-<instance>`)

**Official docs**: https://docs.paloaltonetworks.com/cortex/cortex-xdr/cortex-xdr-api/cortex-xdr-apis/script-execution/get-scripts.html

## Purpose

Get a list of scripts available in the scripts library.

## Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `name` | `List[str]` | `None` | Script names |
| `description` | `List[str]` | `None` | Script descriptions |
| `created_by` | `List[str]` | `None` | Username(s) of who created the script(s). |
| `script_uid` | `List[str]` | `None` | GUID, global ID of the script(s), used to identify the script(s) when executing. |
| `modification_time` | `int` | `None` | Datetime of when the script was last modified. |
| `after_modification` | `bool` | `False` | If the modification date will be the upper or lower bound limit. |
| `windows_supported` | `bool` | `None` | Whether the script can be executed on Windows operating system. |
| `linux_supported` | `bool` | `None` | Whether the script can be executed on Linux operating system. |
| `macos_supported` | `bool` | `None` | Whether the script can be executed on Mac operating system. |
| `is_high_risk` | `bool` | `None` | Whether the script has a high-risk outcome. |

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

An object of type GetScriptsResponse if successful.

## Notes

- This endpoint is a `POST` to the XDR `/public_api/v1/scripts/get_scripts/` path regardless of whether semantically it reads or writes; XDR's REST API uses POST + JSON-body for filtering.
- Generated from `ebarti/cortex-xdr-client`'s `get_scripts` wrapper — see https://github.com/ebarti/cortex-xdr-client for the authoritative Python implementation.
- Bearer auth headers are computed by the connector's `_xdr_client.py`; the tool function itself doesn't see raw credentials.
- Rate-limit + retry behavior per XDR tenant — consult the official docs at the link above for current limits.

## Cross-references

- Phantom tool: `bundles/spark/connectors/cortex-xdr/src/connector.py` → `xdr_scripts_list`
- Source mapping: `ebarti/cortex_xdr_client/api/scripts_api.py` → `get_scripts`
