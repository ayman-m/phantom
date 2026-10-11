---
id: XQL-165-xdr-network-egress-by-host
title: Cortex XDR — outbound network egress per source IP (XDR pattern)
category: investigation
dataset: xdr_data
tags:
  - filter
  - comp
  - sort
  - limit
  - xdr_data
  - xdr-pattern
  - network
---

# Cortex XDR — outbound network egress per source IP

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = ENUM.NETWORK
| filter action_remote_ip != null
| filter not incidr(action_remote_ip, "10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8")
| filter _time > to_timestamp(current_time() - duration("PT1H"))
| comp count() as connection_count, sum(action_total_download) as bytes_in, sum(action_total_upload) as bytes_out by agent_hostname, action_remote_ip, action_remote_port, action_app_id_transitions
| sort desc bytes_out
| limit 100
```

## When to use

Operator asks variants of:

- "show me which hosts are talking to public IPs the most"
- "what's the egress volume per endpoint in the last hour"
- "find hosts with high outbound traffic — C2 hunt"

Useful for both threat-hunting (C2 detection — high-volume outbound to a single non-internal IP) and capacity investigation (which endpoints are pushing the most data).

## Variations

- Replace the `incidr` exclusion with an inclusion to focus on intra-network traffic: `| filter incidr(action_remote_ip, "10.0.0.0/8, 192.168.0.0/16")`.
- Pivot to per-app egress: `| comp ... by action_app_id_transitions` (drops `agent_hostname`/`action_remote_ip`) to see which applications dominate egress.
- Specific port hunt: `| filter action_remote_port in (4444, 8443, 53)` for known C2 / DNS-tunneling ports.
- Add a uniqueness gate: `| filter connection_count > 10` to suppress one-shot anomalies.

## Source

Pattern derived from the Cortex XDR Public API + Palo Alto threat-hunting documentation. The `action_*` field family is XDR's network-event shape; field names like `action_remote_ip` / `action_total_download` are stable across XDR releases but tenant-specific dashboards may rename them. Validate against your tenant's `xdr_data` schema before relying on the exact field set.
