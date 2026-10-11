# Get Broker

**HTTP**: `POST /public_api/v1/broker/get_broker/`
**MCP tool**: `xsiam_broker_get`
**Phantom connector**: `xsiam`

## Purpose

Full status + config detail for one broker VM.

## Parameters

| Param | Type | Required | Description |
|---|---|---|---|
| `broker_id` | `str` | yes | From `xsiam_broker_list`. |

## Returns

```json
{ "ok": true, "broker": { "id", "name", "hostname", "version", "status", "config", "metrics" } }
```
