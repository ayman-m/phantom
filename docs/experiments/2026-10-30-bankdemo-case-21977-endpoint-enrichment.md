# BankDemo case 21977 — endpoint enrichment (2026-10-30)

## Objective

Enrich case **21977** (`Insider data theft and fraud attempt - PHANTOM\balomari`) with real XDR endpoint telemetry on the same entities already in the case: `ph-lab-winpc`, `ph-lab-linux`, and `NT AUTHORITY\SYSTEM`. All collected/exported customer records were synthetic lab data. Exfiltration destinations were limited to the phantom VM at `10.10.0.81`.

## Access and agent recovery

- Ayman tenant API and XQL verified through `https://api-ayman.xdr.eu.paloaltonetworks.com`.
- All three XDR endpoints were connected and protected.
- Windows Sandcat agents were redeployed as auto-restarting SYSTEM scheduled tasks using `scripts/experiments/caldera_sandcat_startup.ps1` and a one-time VM restart.
- Fresh Caldera beacons: `ph-lab-winpc` / `vjpduw` at 07:59:53 UTC; `ph-lab-dc` / `dkexeg` at 08:00:21 UTC.
- The XDR agent later flagged Sandcat with Behavioral Threat / WildFire detections. Windows tasks were restarted through XDR endpoint scripting after the simulation.

## Caldera content

Custom adversaries and abilities were created for Windows and Linux. The chains cover host/directory discovery, credential-path discovery, synthetic customer-data collection and archiving, encoded command execution, renamed-LOLBIN staging, cron/scheduled-task persistence, lab-internal service discovery, and controlled exfiltration.

Operations:

| Operation | Caldera ID | UTC start | Result |
|---|---|---|---|
| `bankdemo-insider-linux-v1` | `1a9f67e0-da16-4f67-9ae3-2f834381e1b8` | 07:55:47 | Paused to prioritize Windows recovery; later superseded |
| `bankdemo-insider-windows-v1` | `b42d6ae3-142d-447f-9bd3-b07d8dd088df` | 08:03:45 | Discovery executed; planner repeated first step |
| `bankdemo-insider-windows-v2` | `c10aa36e-e75b-4347-a14d-7c1bee8be02e` | 08:07:46 | Real Windows discovery, credential, collection, encoded execution and scheduled-task telemetry generated |
| `bankdemo-insider-windows-final2` | `9d4cc624-3ec0-45a0-bee0-14cd45e19c51` | 08:40:02 | Planner queued remaining stages; completed through XDR scripting instead |
| `bankdemo-insider-linux-final` | `d9d8304e-1c1f-4865-8cd2-897daac15473` | 08:36:10 | Planner queued stages; completed through XDR scripting instead |

Caldera planner note: the default `Hack the planet` objective caused repeated links. Empty/manual operations also raced with auto-pausing, and `potential-links` requests eventually stalled. The same custom ability payloads were therefore executed through the tenant's built-in `execute_commands` XDR script for deterministic completion.

## Deterministic XDR completion runs

| Host | XDR action | UTC start | Result |
|---|---:|---|---|
| `ph-lab-linux` | 6322 | 08:46:15 | Completed successfully; full seven-stage chain as root |
| `ph-lab-winpc` | 6323 | 08:46:18 | Completed successfully; controlled exfiltration and service discovery |

Temporary persistence was removed afterward (actions 6324 and 6325). Staged synthetic files were retained for demo evidence. Windows Sandcat tasks were restarted with actions 6326 and 6327.

## Tenant outcomes

Three new high-severity endpoint cases were created:

### Case 22022 — ph-lab-winpc

- **WildFire Malware** (high): Sandcat post-detection.
- **Behavioral Threat** (high): Sandcat execution chain.
- **Execution of significantly renamed lolbin** (medium): `.cache-helper.exe`, a renamed copy of `curl.exe`, launched by the custom PowerShell stage.
- **Credential Vault command-line access** (medium): `VaultCmd.exe /list`, with the full parent PowerShell command line and actor attribution.

MITRE coverage includes Execution, Credential Access, Defense Evasion / Masquerading, Collection, and Exfiltration.

### Case 22023 — ph-lab-linux

- Three **Behavioral Threat** alerts (high) tied to cron persistence and the Sandcat process tree.
- **A TCP stream was created directly in a shell** (medium): `/bin/bash -c </dev/tcp/10.10.0.33/22` with process and command-line evidence.

MITRE coverage includes Execution, Persistence / Cron, Privilege Escalation, and command-and-scripting activity.

### Case 22024 — ph-lab-dc

- **WildFire Malware** (high): Sandcat post-detection on `C:\ProgramData\Caldera\sandcat.exe`.

## Demo use

Cases 22022 and 22023 are the endpoint evidence to attach to the case-21977 narrative. They share `ph-lab-winpc`, `ph-lab-linux`, and SYSTEM with the original case. Use the UTC timestamps above to locate the runs. The strongest causality examples are the renamed-curl execution on Windows and the cron/Sandcat process trees on Linux.

For repeated demos, avoid redeploying Sandcat without accounting for the XDR Behavioral Threat / WildFire detections; use the XDR `execute_commands` mechanism for deterministic one-shot stages or configure an explicit lab exception first.
