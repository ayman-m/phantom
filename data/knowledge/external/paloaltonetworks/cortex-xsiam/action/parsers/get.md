# Get Parser

**HTTP**: `POST /public_api/v1/parser/get_parser/`
**MCP tool**: `xsiam_parsers_get`
**Phantom connector**: `xsiam`

## Purpose

Get the full definition of one parser (parsing rules, field mappings, source/destination dataset).

## Parameters

| Param | Type | Required | Description |
|---|---|---|---|
| `parser_id` | `str` | yes | From `xsiam_parsers_list`. |

## Returns

```json
{ "ok": true, "parser": { "id", "name", "rules", "dataset", "vendor", "product" } }
```
