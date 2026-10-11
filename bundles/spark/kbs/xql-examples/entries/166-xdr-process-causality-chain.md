---
id: XQL-166-xdr-process-causality-chain
title: Cortex XDR — process causality chain for a suspicious binary (XDR pattern)
category: investigation
dataset: xdr_data
tags:
  - filter
  - join
  - sort
  - limit
  - xdr_data
  - xdr-pattern
  - causality
---

# Cortex XDR — process causality chain for a suspicious binary

**Dataset**: `xdr_data`

```sql
dataset = xdr_data
| filter event_type = ENUM.PROCESS
| filter agent_hostname = "win-host-01"
| filter actor_process_image_name in ("powershell.exe", "cmd.exe", "wmic.exe", "rundll32.exe")
| fields _time, agent_hostname, actor_process_image_name, actor_process_command_line, causality_actor_process_image_name, causality_actor_process_command_line, action_process_image_name, action_process_command_line
| sort asc _time
| limit 200
```

## When to use

Operator asks variants of:

- "what's the parent of this powershell instance?"
- "show me the causality chain on `<host>` for living-off-the-land binaries"
- "trace the process tree after the Caldera operation"

XDR's causality model: every PROCESS event carries `causality_actor_*` (the original parent triggering the chain) and `action_*` (the child process this event acted on). Filtering on `actor_*` shows what's running NOW; including `causality_*` shows where the chain originated. Pairs naturally with the Caldera detection-validation loop — fire an operation, then run this query to see the parent → child tree the operation produced.

## Variations

- Investigate ONE process by name: `| filter actor_process_image_name = "powershell.exe"` (drop the list).
- Trace a specific causality root: add `| filter causality_actor_process_image_name = "explorer.exe"` to see all children of a known-good parent (highlights deviation from interactive-user workflows).
- Add command-line content search: `| filter actor_process_command_line ~= "Invoke-Expression|DownloadString|EncodedCommand"` — catches PowerShell offensive patterns. (`~=` is XQL's case-insensitive regex match.)
- Pivot to network-event correlation: keep this query small (limit 50), then run query 165 (egress-by-host) on the same hostname + time window to cross-correlate process-spawn against outbound traffic.

## Source

Pattern derived from the Cortex XDR Public API + Palo Alto threat-hunting documentation. The `causality_actor_*` field family is XDR's signature causality model — well-stabilized across XDR releases. Field names are reliable; the *content* of which processes count as "suspicious" is operator + environment-specific. Validate against your tenant before treating any specific binary list as exhaustive.
