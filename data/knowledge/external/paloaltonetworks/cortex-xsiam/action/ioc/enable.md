# Enable IoCs

**HTTP**: `POST /public_api/v1/indicators/enable_iocs/`
**MCP tool**: `xsiam_ioc_enable`

## Purpose

Re-enable previously disabled IoCs. Mirror of `xsiam_ioc_disable` — same argument shape, opposite effect.

## Parameters

| Param | Type | Required | Description |
|---|---|---|---|
| `indicators` | `list[str]` | yes | IoC VALUE strings to re-enable. |

## Request body

```json
{ "request_data": { "indicators": ["malicious.example.com"] } }
```

## Returns

```json
{ "ok": true, "enabled_count": 1, "indicators": [...] }
```

## Cross-references

- Phantom tool: `bundles/spark/connectors/xsiam/src/connector.py` → `xsiam_ioc_enable`
