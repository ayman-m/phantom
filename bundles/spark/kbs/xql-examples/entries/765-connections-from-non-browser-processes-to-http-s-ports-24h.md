---
id: XQL-765-6c1e36e4
title: Connections from non-browser processes to HTTP/S ports (24h)
category: detection
dataset: xdr_data
tags:
  - filter
  - comp
  - sort
  - limit
  - xdr_data
  - network
---

# Connections from non-browser processes to HTTP/S ports (24h)

**Dataset**: `xdr_data`

```sql
config timeframe = 24h
| dataset = xdr_data
| filter event_type = ENUM.NETWORK and action_remote_port in (80, 443, 8080)
| filter lowercase(actor_process_image_name) not in ("chrome.exe", "firefox.exe", "msedge.exe", "iexplore.exe", "safari.exe", "opera.exe", "brave.exe", "svchost.exe", "system")
| comp count() as cnt by actor_process_image_name
| sort desc cnt
| limit 10
```

## When to use

Non-browser processes making web requests. Often legitimate (update agents, telemetry) but a useful triage starting-point for finding rogue clients that shouldn't be talking to the internet.

## Variations

_(No variations are documented for this entry.)_
