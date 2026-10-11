---
id: XQL-712-533d4d23
title: Outbound connections to public IPs from internal hosts (24h)
category: detection
dataset: xdr_data
tags:
  - filter
  - comp
  - sort
  - limit
  - xdr_data
  - network
  - incidr
---

# Outbound connections to public IPs from internal hosts (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK
| filter not incidr(action_remote_ip, "10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8, 169.254.0.0/16")
| comp count() as connections, sum(action_total_upload) as upload_bytes by agent_hostname, action_remote_ip
| sort desc upload_bytes
| limit 10
```

## When to use

Outbound connections to public (non-RFC1918) IP space. Useful for surfacing legitimate-vs-suspicious external traffic. The `incidr` function with negation filters out internal-network traffic.

## Variations

_(No variations are documented for this entry.)_
