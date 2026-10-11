# Describe Datamodel

**HTTP**: `POST /public_api/v1/xql/start_xql_query/` with `dataset = X | datamodel`
**MCP tool**: `xsiam_datamodel_describe`
**Phantom connector**: `xsiam`

## Purpose

XSIAM-licensed datamodel introspection. Returns the XDM-typed schema for a dataset (field names + types + descriptions). Use to discover what fields are available for XQL query construction.

## Parameters

| Param | Type | Required | Description |
|---|---|---|---|
| `dataset` | `str` | yes | Dataset name (e.g. `xdr_data`, `endpoints`, `alerts`). |

## Returns

```json
{ "ok": true, "dataset": "xdr_data", "fields": [{ "name", "type", "description" }] }
```

## Notes

- **XSIAM-license-gated** — XDR-only tenants return "Invalid License - XSIAM" for this query.
- Internally builds an XQL query with the `datamodel` stage + executes via `xsiam_xql_run_query`.
- Pair with `xsiam_get_datasets` to find candidate datasets, then describe each.
