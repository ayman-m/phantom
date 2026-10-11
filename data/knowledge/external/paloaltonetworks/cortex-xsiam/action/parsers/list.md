# List Parsers

**HTTP**: `POST /public_api/v1/parser/get_parsers/`
**MCP tool**: `xsiam_parsers_list`
**Phantom connector**: `xsiam`

## Purpose

List parsers configured in the XSIAM tenant. Parsers transform raw vendor logs into the XDM schema. Use to audit what vendor sources have parsers deployed.

## Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `vendor` | `str` | `None` | Filter by vendor name. |
| `product` | `str` | `None` | Filter by product within vendor. |
| `enabled` | `bool` | `None` | Filter by enabled state. |

## Returns

```json
{ "ok": true, "parsers": [{ "id", "name", "vendor", "product", "enabled", "modified_at" }] }
```

## Notes

- Hand-authored R5.3 from public XSIAM docs knowledge — verify against tenant.
- XSIAM-unique (XDR doesn't expose parsers — they're managed via the modeling-rule pipeline instead).
