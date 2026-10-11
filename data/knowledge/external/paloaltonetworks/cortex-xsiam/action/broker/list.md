# List Brokers

**HTTP**: `POST /public_api/v1/broker/list_brokers/`
**MCP tool**: `xsiam_broker_list`
**Phantom connector**: `xsiam`

## Purpose

List XSIAM Broker VMs deployed in this tenant. Brokers are data-collector VMs that bridge on-prem log sources to XSIAM cloud.

## Returns

```json
{ "ok": true, "brokers": [{ "id", "name", "hostname", "version", "status", "last_seen" }] }
```

## Notes

- Hand-authored R5.3 from public XSIAM docs — verify against tenant.
