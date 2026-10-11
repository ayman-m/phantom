# Disable IoCs

**HTTP**: `POST /public_api/v1/indicators/disable_iocs/`
**MCP tool**: `xdr_ioc_disable`

**Official docs**: https://docs.paloaltonetworks.com/cortex/cortex-xdr/cortex-xdr-api/cortex-xdr-apis/threat-intelligence-management

## Purpose

Disable one or more IoCs — XDR stops alerting/blocking on them. Use when an operator finds a false-positive entry from a feed and wants to silence it without removing it entirely.

## Parameters

| Param | Type | Required | Description |
|---|---|---|---|
| `indicators` | `list[str]` | yes | IoC VALUE strings (not IDs) — e.g. `["malicious.example.com", "1.2.3.4"]`. |

## Request body

```json
{ "request_data": { "indicators": ["malicious.example.com", "1.2.3.4"] } }
```

## Returns

```json
{ "ok": true, "disabled_count": 2, "indicators": [...] }
```

## Cross-references

- Phantom tool: `bundles/spark/connectors/cortex-xdr/src/connector.py` → `xdr_ioc_disable`
- Companion: `xdr_ioc_enable` (re-enables); `xdr_ioc_insert_json` (initial upload).
