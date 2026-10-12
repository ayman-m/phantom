---
name: malicious_email_to_endpoint_persistence
displayName: Email malware persistence
category: scenarios
description: 'Four-stage email-to-endpoint compromise chain. Stage 1: phishing email delivers a macro-document. Stage 2: EDR sees Office spawning PowerShell with encoded arguments. Stage 3: credential-access activity (LSASS handle, suspicious memory read). Stage 4: defense evasion + persistence (security agent tamper, scheduled task install). Vendor-agnostic — agent resolves vendor/product from the operator''s installed data sources at runtime. Triggers 4 XSIAM rules: Phishing email with malicious attachment, Suspicious PowerShell, LSASS / Credential Dump, EDR / Defender Tamper.'
icon: dangerous
source: platform
loadingMode: on-demand
locked: false
attack:
  - 'TA0001: Initial Access (T1566.001 Spearphishing Attachment)'
  - 'TA0002: Execution (T1059.001 PowerShell, T1204.002 Malicious File)'
  - 'TA0003: Persistence (T1053.005 Scheduled Task)'
  - 'TA0005: Defense Evasion (T1562.001 Disable Security Tools)'
  - 'TA0006: Credential Access (T1003.001 LSASS Memory)'
---

# Skill: Malicious email → Endpoint compromise → Persistence

## Category

scenarios

## Attack Type

The classic "open the attachment" intrusion — phishing email with a weaponized Office document, macro execution spawning a PowerShell child process, in-memory implant deploying, credential theft, and persistence + defense evasion to maintain access. This is the most-common ransomware-precursor pattern in 2024-26 IR engagements.

## MITRE ATT&CK Tactics

- TA0001: Initial Access (T1566.001 Spearphishing Attachment)
- TA0002: Execution (T1059.001 PowerShell, T1204.002 Malicious File)
- TA0003: Persistence (T1053.005 Scheduled Task)
- TA0005: Defense Evasion (T1562.001 Disable Security Tools)
- TA0006: Credential Access (T1003.001 LSASS Memory)

## XSIAM analytics rules triggered

| # | Rule | Stage |
|---|---|---|
| 9 | Phishing email with malicious attachment | Stage 1 |
| 13 | Suspicious PowerShell (encoded / lolbin args) | Stage 2 |
| 14 | LSASS / Credential Dump | Stage 3 |
| 19 | EDR / Defender Tamper | Stage 4 |

## Data classes used

| Stage | Data class | If missing |
|---|---|---|
| 1 | `email-gateway` | Required |
| 2, 3, 4 | `edr` | Required |

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
3. Both `email-gateway` (Stage 1) and `edr` (Stages 2-4) are required; Stages 2-4 need the process tree, command line and memory-access events that only endpoint telemetry carries, and network-tier substitutions do not capture them. If it is `MISSING`, say this to the operator, with the class filled in: "No installed data source covers the `<class>` class, so I cannot run the email malware persistence scenario. Install a `<class>` data source from the Marketplace and ask again." Then stop: create no worker.
4. In your final report, list every stage you skipped or substituted and which of the alerts above will therefore not fire.

## Narrative thread

- **Phishing sender:** `invoices@panapay-procurement.com` (typo-squat of legitimate-looking procurement domain)
- **Phishing subject:** `[ACTION REQUIRED] Q4 procurement statement — ref INV-2891`
- **Attachment:** `Q4-Procurement-Statement.docm` (Word doc with malicious macro)
- **Attachment SHA-256:** `b42c1f9e3a0d7c8b5e2f4a6d8e1b3c5a7f9d2e4b6c8a0d2f4e6c8a0b2d4f6c8e`
- **Target user:** `l.thomas@corp.example`
- **Target user IP:** `10.10.20.78`
- **Target hostname:** `wks-lthomas-01`
- **C2 IP (PowerShell stager pulls from):** `91.243.59.108`
- **C2 domain:** `cdn-update-svc.tk` (resolved via the DNS tunneling pattern from the dns_tunneling_c2 skill, optionally chain it)
- **Wall-clock time:** Stage 1 instant. Stage 2 ~5 min after delivery (user opens attachment). Stage 3 ~3 min after Stage 2 (post-implant credential harvest). Stage 4 ~2 min after Stage 3 (persistence + tamper).

---

### Stage 1 — Malicious email delivered — ~30 events over 60 seconds

The malicious email lands. As with the phishing skill, generate noise + the malicious entry. This time the malicious one carries a macro-document attachment.

**Data class:** `email-gateway`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[email-gateway].vendor>
  product: <stack[email-gateway].product>
  count:    30
  interval: 2
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    senderEmail:    ["partners@example-supplier.com",
                      "noreply@hr-internal.corp.example",
                      "invoices@panapay-procurement.com"]
    senderDomain:   ["example-supplier.com",
                      "hr-internal.corp.example",
                      "panapay-procurement.com"]
    recipientEmail: ["l.thomas@corp.example",
                      "team-procurement@corp.example"]
    emailSubject:   ["Q4 supplier review",
                      "Internal HR newsletter",
                      "[ACTION REQUIRED] Q4 procurement statement — ref INV-2891"]
    attachmentName: ["",
                      "",
                      "Q4-Procurement-Statement.docm"]
    attachmentHash: ["",
                      "",
                      "b42c1f9e3a0d7c8b5e2f4a6d8e1b3c5a7f9d2e4b6c8a0d2f4e6c8a0b2d4f6c8e"]
    attachmentCount: ["0", "0", "1"]
    act:          ["delivered"]
    threatCategory: ["clean", "clean", "macro_document"]
    threatScore:    ["10", "20", "78"]
    cefSeverity:        ["informational", "high"]
```

**Field semantics:**
- `attachment_name: *.docm` — the `.docm` extension explicitly enables macros (`.docx` does not). Most enterprises block `.docm` from external senders, but the user's policy may flag-rather-than-block
- `attachment_hash` — SHA-256 of the malicious doc. Threat-intel feeds tag known-bad hashes; even unknown hashes raise risk when combined with other signals
- `sandbox_verdict: suspicious` — modern email gateways send attachments to a sandbox and enrich with the verdict
- `threat_category: macro_document` + `threat_score: 78` — the gateway scored it suspicious but didn't outright block (many enterprises set the block threshold at 90+; this lands in the "deliver with warning banner" range)
- `domain_age_days: 21` — `panapay-procurement.com` is 3 weeks old; legitimate procurement domains are years old

**Why this fires Rule #9:** the `attachment_count=1` + `file_extension=docm` + `sandbox_verdict=suspicious` + young sender domain combo crosses the SIEM's "suspicious attachment delivered" threshold.

---

### Stage 2 — Macro execution → PowerShell stager — ~8 events over 30 seconds

Five minutes after delivery, `l.thomas` opens the document. The macro launches PowerShell with a base64-encoded payload. EDR sees the parent-child relationship `WINWORD.EXE → cmd.exe → powershell.exe` and the encoded command-line.

**Data class:** `edr`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[edr].vendor>
  product: <stack[edr].product>
  count:    8
  interval: 4
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    shost:        ["wks-lthomas-01"]
    src:          ["10.10.20.78"]
    suser:            ["l.thomas"]
    sproc:    ["WINWORD.EXE", "cmd.exe", "powershell.exe"]
    parentProcessName:  ["explorer.exe", "WINWORD.EXE", "cmd.exe"]
    commandLine:    ["WINWORD.EXE /n \"C:\\Users\\l.thomas\\Downloads\\Q4-Procurement-Statement.docm\"",
                      "cmd.exe /c powershell.exe -nop -w hidden -ep bypass -enc <300+ chars base64>",
                      "powershell.exe -nop -w hidden -ep bypass -enc <300+ chars base64>"]
    fileHash:       ["5cae0e91 (renamed system process)"]
    filePath:       ["C:\\Program Files\\Microsoft Office\\WINWORD.EXE",
                      "C:\\Windows\\System32\\cmd.exe",
                      "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"]
    act:          ["process_create"]
    cefSeverity:        ["medium", "high", "high"]
    alertName:      ["Office application spawned PowerShell with encoded command",
                      "PowerShell encoded payload exceeds 300 chars (typical of stager)"]
    alertType:      ["edr_alert"]
    attackType:     ["powershell_encoded", "office_spawn_lolbin"]
    attackSeverity: ["high"]
    mitreTechnique: ["T1059.001", "T1204.002"]
```

**Field semantics:**
- `process_name` chain: `WINWORD.EXE → cmd.exe → powershell.exe` — Office should NEVER spawn PowerShell in normal use. The parent-child relationship alone is a strong signal
- `command_line` — `-nop` (no profile), `-w hidden` (hidden window), `-ep bypass` (execution-policy bypass), `-enc <base64>` — this combination of flags is the canonical "I'm running an attacker stager" signature. Length of the encoded string is also diagnostic; >300 chars typically means a real stager (small commands fit in <100 chars)
- `mitre_technique` — populating ATT&CK technique IDs lets the SIEM's MITRE-mapped detection content match cleanly
- `severity / alert_severity` — populated so SIEM triage assigns priority correctly

**Why this fires Rule #13:** the "Office spawns PowerShell with `-enc`" pattern is the textbook macro-stager detection. Some SIEMs use the parent-child relationship; others key on `-enc` flag presence; high-fidelity rules combine both.

---

### Stage 3 — Credential access (LSASS memory read) — ~5 events over 60 seconds

Three minutes after the PowerShell stager runs, the implant attempts to harvest credentials. The most reliable EDR-visible pattern is opening a handle to `lsass.exe` with read access. Two common variants:
- LOLBin: `comsvcs.dll` MiniDump function (line-noise stage)
- Direct: process opens `lsass.exe` PID with `PROCESS_VM_READ` rights

**Data class:** `edr`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[edr].vendor>
  product: <stack[edr].product>
  count:    5
  interval: 12
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    shost:        ["wks-lthomas-01"]
    src:          ["10.10.20.78"]
    suser:            ["l.thomas"]
    sproc:    ["powershell.exe", "rundll32.exe"]
    parentProcessName:  ["powershell.exe"]
    commandLine:    ["powershell.exe -nop -w hidden -ep bypass -enc <300+ chars>",
                      "rundll32.exe C:\\Windows\\System32\\comsvcs.dll, MiniDump <lsass-pid> C:\\Windows\\Temp\\dbg.bin full"]
    targetProcessName:  ["lsass.exe"]
    targetPid:      ["604", "604", "604"]
    accessMask:     ["0x1410", "0x1FFFFF"]
    accessList:   ["PROCESS_VM_READ", "PROCESS_QUERY_INFORMATION", "PROCESS_ALL_ACCESS"]
    act:          ["process_access", "process_handle_open", "memory_read"]
    whenCreated:    ["", "", "C:\\Windows\\Temp\\dbg.bin"]
    fsize:       ["", "", "62914560"]
    cefSeverity:        ["critical"]
    alertName:      ["LSASS Memory Access via Suspicious Process",
                      "comsvcs.dll MiniDump LOLBin Pattern Detected"]
    attackType:     ["lsass_dump", "credential_dump"]
    attackSeverity: ["critical"]
    mitreTechnique: ["T1003.001"]
```

**Field semantics:**
- `target_process: lsass.exe` — LSASS is the Local Security Authority Subsystem; it holds credential material. Reading its memory == credential theft
- `access_mask: 0x1410` — `PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ` — the read-with-query mask is what LSASS dumpers request. Legitimate processes (task manager, EDR itself) use different masks
- `command_line` showing `comsvcs.dll, MiniDump <pid>` — the canonical LOLBin pattern. `comsvcs.dll` is a Windows-signed DLL that exports a MiniDump function; rundll32 invokes it
- `file_created: C:\Windows\Temp\dbg.bin` + `file_size: 60+ MB` — LSASS memory is typically 30-100 MB; a binary file of that size in a temp directory is the dump artifact

**Why this fires Rule #14:** the EDR's LSASS-access detection is high-fidelity in modern products. Combining `target_process=lsass.exe` + `access_mask=0x1410` + suspicious-source-process (rundll32 with comsvcs.dll args) is unmistakable. Even if the dump file were never written to disk, the access alone fires.

---

### Stage 4 — Defense evasion + persistence — ~6 events over 90 seconds

After credentials are exfiltrated to C2, the attacker installs persistence and disables the security product. Two parallel substages.

**Sub-stage 4A — security tool tamper**

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[edr].vendor>
  product: <stack[edr].product>
  count:    3
  interval: 8
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    shost:        ["wks-lthomas-01"]
    src:          ["10.10.20.78"]
    suser:            ["l.thomas", "SYSTEM"]
    sproc:    ["powershell.exe", "sc.exe"]
    parentProcessName:  ["powershell.exe"]
    commandLine:    ["powershell.exe Set-MpPreference -DisableRealtimeMonitoring $true",
                      "powershell.exe Set-MpPreference -DisableBehaviorMonitoring $true",
                      "sc.exe stop WinDefend"]
    serviceState:   ["stopped", "stop_pending"]
    act:          ["service_stop", "registry_modify", "configuration_change"]
    registryKey:    ["HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows Defender\\DisableAntiSpyware"]
    registryValueData:  ["1"]
    cefSeverity:        ["critical"]
    alertName:      ["Security Service Tampered — Defender Disabled",
                      "Realtime Protection Disabled via PowerShell"]
    attackType:     ["security_tool_tamper", "defender_disable"]
    attackSeverity: ["critical"]
    mitreTechnique: ["T1562.001"]
```

**Sub-stage 4B — scheduled task persistence**

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[edr].vendor>
  product: <stack[edr].product>
  count:    3
  interval: 5
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    shost:        ["wks-lthomas-01"]
    src:          ["10.10.20.78"]
    suser:            ["l.thomas"]
    sproc:    ["schtasks.exe", "powershell.exe"]
    parentProcessName:  ["powershell.exe"]
    commandLine:    ["schtasks.exe /create /sc onlogon /tn \"WindowsUpdateChk\" /tr \"powershell.exe -nop -w hidden -ep bypass -file C:\\Users\\Public\\update.ps1\" /rl highest /f",
                      "schtasks.exe /run /tn WindowsUpdateChk"]
    taskName:       ["WindowsUpdateChk"]
    runLevel:  ["HIGHEST"]
    whenCreated:    ["C:\\Users\\Public\\update.ps1"]
    fsize:       ["8420"]
    act:          ["scheduled_task_create"]
    cefSeverity:        ["high"]
    alertName:      ["Persistence — Scheduled Task with PowerShell Action"]
    attackType:     ["persistence_scheduled_task"]
    attackSeverity: ["high"]
    mitreTechnique: ["T1053.005"]
```

**Field semantics:**
- `Set-MpPreference -DisableRealtimeMonitoring $true` — the canonical PowerShell command to disable Windows Defender real-time protection. Any modern EDR detects this command-line directly
- `sc.exe stop WinDefend` — the service-level stop. Again, EDR-detected
- `task_trigger: onlogon` + `task_action` running PowerShell hidden — the persistence mechanism. The fact that `l.thomas` (regular user) is creating a high-rights scheduled task that runs at every logon is the strong signal
- `file_created: C:\Users\Public\update.ps1` — Public is world-writable, doesn't trigger UAC, and is a common attacker drop location

**Why this fires Rule #19:** EDR products universally detect their own service being stopped. The `Set-MpPreference -DisableRealtimeMonitoring` PowerShell pattern is a top-tier alert in any modern EDR. Combined with the post-LSASS-dump context, this fires high-confidence "endpoint compromise complete" alerts.

---

## Verification

| Indicator | Where to check |
|---|---|
| Phishing email alert with `attachment_hash=b42c1f9e...` | XSIAM Issues |
| EDR alert: Office spawns PowerShell with encoded args | XSIAM Issues |
| EDR alert: LSASS memory access | XSIAM Issues |
| EDR alert: Defender disabled | XSIAM Issues |
| EDR alert: Persistence scheduled task | XSIAM Issues (sometimes filed under same incident as tamper) |
| Pivotable: filter by host=`wks-lthomas-01`, see all 4 stages on one timeline | XQL: `config timeframe = 24h \| dataset = <dataset_name of the edr entry> \| filter <its host field> = "wks-lthomas-01" \| limit 20` |

## Tear-down

```yaml
xlog.list_workers:
xlog.kill_worker:
  worker_id: <each>
```

## Adapting per deployment

The attachment hash `b42c1f9e...` and PowerShell encoded payload are illustrative. For exercises tied to a real customer's threat-model, swap in hashes from the customer's threat-intel feed so their existing TI integrations also enrich the alerts.
