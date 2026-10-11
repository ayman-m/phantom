# Phantom Caldera kill-chain content

Caldera abilities + adversary profile that simulate a complete phishing →
ransomware kill chain across **two Windows agents** (attacker + victim).
Generates realistic Sysmon / Windows Security telemetry at every stage so
operators can exercise their SOC detection rules against a known-good
attack sequence.

This content is **baked into the phantom-caldera image** and auto-loaded by
Caldera on every fresh install. The YAMLs in this directory are copied into
the image at `/usr/src/app/data/{abilities,adversaries}/` at build time, and
Caldera's `data_svc.py` scans those directories on container start. No
manual UI import is needed.

---

## What's in this kill chain (20 steps)

20 MITRE ATT&CK techniques across 11 tactics. 14 abilities are
custom-built for this lab (in `abilities/`); the other 6 are referenced
from Caldera's bundled stockpile plugin.

| # | Tactic | Technique | Ability source |
|---|---|---|---|
| 1 | initial-access | T1566.001 Spearphishing Attachment | custom (`01-initial-access/phishing-emailclient-spawn.yml`) |
| 2 | execution | T1059.003 Windows Command Shell | stockpile `9003977f` |
| 3 | discovery | T1087.001 Local Account Discovery | custom (`03-discovery/account-system-discovery.yml`) |
| **4** | **discovery** | **T1082 System Information Discovery** (+ T1018) | **custom (`03-discovery/system-info-burst.yml`)** |
| **5** | **discovery** | **T1135 Network Share Discovery** | **custom (`03-discovery/network-share-discovery.yml`)** |
| 6 | credential-access | T1003.005 Cached Credentials | stockpile `bb0df721` |
| **7** | **credential-access** | **T1003.001 LSASS Memory (comsvcs.dll minidump)** | **custom (`04-credential-access/lsass-minidump-comsvcs.yml`) — marquee XDR signal** |
| 8 | privilege-escalation | T1548.002 Fodhelper UAC Bypass | stockpile `20d68348` |
| **9** | **defense-evasion** | **T1562.001 Disable Defender Real-time** | **custom (`05-defense-evasion/disable-defender-realtime.yml`)** |
| **10** | **defense-evasion** | **T1140 Certutil Decode (LOLBin)** | **custom (`05-defense-evasion/certutil-decode-payload.yml`)** |
| 11 | persistence | T1136.001 Create Local Account | stockpile `f39aace7` |
| **12** | **persistence** | **T1547.001 Registry Run Key** | **custom (`06-persistence/registry-run-key.yml`)** |
| **13** | **persistence** | **T1053.005 Scheduled Task `onlogon`** | **custom (`06-persistence/scheduled-task-logon.yml`)** |
| 14 | **lateral-movement** | **T1021.002 SMB/Admin Shares** | **custom (`07-lateral-movement/lateral-smb-wmi-winrm.yml`)** |
| 15 | collection | T1119 Automated Collection | custom (`08-collection/automated-collection-safe.yml`) |
| 16 | collection | T1560 Archive Collected Data | stockpile `8cd2639c` |
| 17 | command-and-control | T1071.004 DNS C2 | custom (`10-command-and-control/dns-beacon-simple.yml`) |
| 18 | exfiltration | T1041 Exfil over C2 | custom (`11-exfiltration/exfil-staged-loot.yml`) |
| 19 | impact | T1491 Defacement | stockpile `47d08617` |
| **20** | **defense-evasion (cleanup)** | **T1070.001 Clear Security Event Log** | **custom (`13-cleanup/clear-security-eventlog.yml`) — Security 1102 fires unconditionally** |

Plus three setup / bootstrap abilities (NOT in the kill chain itself —
run them once before the first execution):

| Tactic | Ability | What it does |
|---|---|---|
| defense-evasion | `00-bootstrap/bootstrap-win-host-02-victim.yml` | Configures the VICTIM host (win-host-02): opens SMB firewall, enables WinRM with `Service\AllowUnencrypted=true` + Basic auth, sets `LocalAccountTokenFilterPolicy=1` for workgroup admin tokens. Add the `phantomlab` local admin user. **Run once on `group=victim`.** |
| defense-evasion | `00-bootstrap/bootstrap-win-host-01-attacker.yml` | Configures the ATTACKER host (win-host-01): WinRM `Client\TrustedHosts` + `AllowUnencrypted` + Basic auth, pre-caches `phantomlab` creds via `cmdkey` for the target. **Run once on `group=red`.** |
| persistence | `06-persistence/create-phantomlab-user-localadmin.yml` | If the bootstrap-victim ability didn't successfully create the `phantomlab` user (silent `New-LocalUser` complexity errors with passwords that contain the username), this ability uses an ASCII-only password (`PhantomLab2026X`) that satisfies Windows complexity rules. **Run on `group=victim` if the bootstrap's user creation failed.** |

---

## XDR detection coverage

The 20-step chain fires across these distinct event sources.
Build correlation rules across steps to detect the WHOLE kill chain
rather than any single technique in isolation — the chain narrative is
the high-confidence signal.

| Step | Event source | Detection rule example |
|---|---|---|
| 1 | Sysmon EID 1 (process create) | `Image` ends in `emailclient.exe` but `OriginalFileName=NOTEPAD.EXE` → masquerade (T1036.005) |
| 2 | Sysmon EID 1 + 11 | `cmd.exe` writes `.cmd`/`.bat`/`.ps1` then runs it from TEMP |
| 3 | Sysmon EID 1 | `whoami` / `Get-LocalUser` / `query session` burst |
| **4** | **Sysmon EID 1 (4-LOLBin burst)** | **`systeminfo`, `arp`, `netstat`, `route` within 5s window — high-confidence discovery burst** |
| **5** | **Sysmon EID 1 + Microsoft-Windows-SMBClient EID 30622** | **`net share`, `net view`, `Get-SmbShare` — share enum** |
| 6 | Sysmon EID 1 | `cmdkey.exe` execution (rare in benign workflows) |
| **7** | **Sysmon EID 10 + EID 11 (high-criticality)** | **`rundll32.exe` opens handle to `lsass.exe` then writes `.dmp` to TEMP — marquee EDR rule (every modern XDR flags this)** |
| 8 | Sysmon EID 13 | Registry value SET at `HKCU\software\classes\ms-settings\shell\open\command\` |
| **9** | **Microsoft-Windows-Windows Defender/Operational 5001 + 5007** | **Defender real-time monitoring disabled + exclusion path added — Defender's own canary fires** |
| **10** | **Sysmon EID 1 + 11** | **`certutil.exe -decode` with file output to TEMP — LOLBin abuse** |
| 11 | Security 4720 | Account creation event (note: status=1 in Caldera but the event fires) |
| **12** | **Sysmon EID 13** | **Registry value SET under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` → boot persistence** |
| **13** | **Security 4698 + Microsoft-Windows-TaskScheduler/Operational 106** | **Scheduled task created with `/sc onlogon /ru SYSTEM /rl HIGHEST`** |
| 14 | **Sysmon EID 3 + Security 4624 + 4672** | **Outbound TCP 445 + 5985 to internal IP, followed by NTLM auth on target host as `phantomlab`, then remote process creation** |
| 15 | Sysmon EID 11 | High-volume file enumeration in user profile dirs |
| 16 | Sysmon EID 1 + 11 | PowerShell + `Compress-Archive` → `.zip` in TEMP |
| 17 | Sysmon EID 22 (DNS query) | 10 distinct queries to subdomains of `.invalid` TLD |
| 18 | Sysmon EID 3 | Outbound HTTP POST with base64 body to internal IP |
| 19 | Sysmon EID 11 | `.txt` create in user-visible directory with "ransom"-style filename |
| **20** | **Security 1102 (Microsoft's "log was cleared" event)** | **Security event log cleared via `wevtutil cl Security` — 1102 fires UNCONDITIONALLY (cannot be suppressed)** |

The marquee detection signals are steps **7** (LSASS dump), **9**
(Defender tamper), **14** (lateral move), and **20** (event log clear)
— these are the high-confidence atomic alerts. Steps **3-5**
(discovery burst) and **11-13** (persistence trio) are best detected as
*sequences* of related lower-confidence events.

---

## Prerequisites

| Requirement | Why |
|---|---|
| **Two Windows agents** in Caldera with sandcat running. One in `group=red` (the "attacker" — win-host-01), one in `group=victim` (win-host-02). | The lateral step (#14) cross-host executes from red → victim. The non-lateral steps run only on `group=red`. |
| **Both agents on the same internal subnet** with no firewall blocking SMB (TCP 445) or WinRM (TCP 5985) between them. | Lateral move uses both protocols. |
| **Both agents elevated** (sandcat started as Administrator). | UAC bypass, create user, firewall changes, Defender tamper, scheduled task creation, event log clear all require admin. |
| **Victim agent's password for `phantomlab`** known to both bootstraps. The default in our YAMLs is `PhantomLab2026X`. | Hardcoded credentials are deliberate — this is a lab simulation, not stealth tradecraft. |

---

## Installation (auto-loaded)

**No manual installation steps needed.** Fresh `sudo /opt/phantom/phantom-installer`
(or `dev-installer`) installs ship the kill-chain content baked into
the phantom-caldera image. On Caldera container start, `data_svc.py`
scans `/usr/src/app/data/abilities/*` and `/usr/src/app/data/adversaries/*`
and registers everything automatically.

Verify after install:

1. Open the Caldera UI (`https://<caldera-host>:8888` in a browser).
2. Login (`red` / `$CALDERA_RED_PASSWORD` from `/opt/phantom/.env`).
3. **Navigate → Adversaries** — find `Phantom phishing -> ransomware kill chain (cross-host, expanded)`.
4. The 20 atomic_ordering entries should all resolve to ability names (not "Missing ability" by UUID).
5. **Navigate → Abilities** — search "Phantom" or filter by tactic; the 14 custom abilities + 6 stockpile references should be present.

If any step shows as "Missing ability" by UUID, the corresponding
stockpile ability isn't loaded — confirm the `stockpile` plugin is
enabled in your Caldera (it is by default in the Phantom-shipped
caldera image).

### Optional: re-import a single ability after edits

If you edit one of the YAMLs in `bundles/spark/caldera-content/abilities/`
and want to test the change without rebuilding the phantom-caldera image:

1. Open the Caldera UI **Advanced → Abilities → Import YAML**.
2. Paste the edited YAML — the existing ability is overwritten by UUID match.
3. Run the operation; the new version takes effect immediately.

For the change to land in the image, rebuild the phantom-caldera image;
the content in this directory is baked in at build time.

---

## How to run

```
                ┌──────────────────────────────────────────┐
                │  ONE-TIME SETUP (run each ability once)  │
                └──────────────────────────────────────────┘
                                  │
        ┌─────────────────────────┴─────────────────────────┐
        │                                                   │
        ▼                                                   ▼
  Operation A: bootstrap-                            Operation B: bootstrap-
  win-host-02-victim                                   win-host-01-attacker
  target group=victim                                target group=red
        │                                                   │
        └─────────────────────────┬─────────────────────────┘
                                  │ (if create-phantomlab user step in
                                  │  bootstrap-victim silently failed,
                                  │  run create-phantomlab separately)
                                  ▼
                ┌──────────────────────────────────────────┐
                │   MAIN OPERATION (run anytime after)     │
                └──────────────────────────────────────────┘
                                  │
                                  ▼
       Operation: Phantom phishing -> ransomware kill chain
       adversary: phantom-phishing-kill-chain
       planner: atomic
       group: red (win-host-01 only — lateral step reaches win-host-02 via SMB)
```

Expected runtime: 10-14 minutes for the 20-step main chain. Bootstraps are ~20s
each.

---

## Lab-safety notes

- **No actual encryption.** Step 19 (Impact / Defacement) drops a text note — does NOT encrypt files. Detection rules that key on the note's filename pattern fire identically to actual ransomware.
- **No actual exfiltration.** Step 18 (Exfil) POSTs to `10.0.0.81:8888` (Caldera's internal listener). The server returns HTTP 500 — that's expected. The outbound POST telemetry is what matters for detection.
- **No real malware payloads.** The "attachment" dropped in step 1 is a plain text file with the right `.docx` extension. The `emailclient.exe` process is a renamed `notepad.exe` (signed Microsoft binary). Step 10 (`certutil -decode`) decodes a harmless base64 text string, not an executable.
- **LSASS dump is captured then deleted (step 7).** The `.dmp` file lands in `C:\Windows\Temp\lsass-*.dmp` and is removed immediately by the ability's own cleanup. On Defender-enabled hosts, Defender blocks the write (expected) — the LSASS-access detection event still fires either way.
- **Defender tamper is reversible (step 9).** `Set-MpPreference -DisableRealtimeMonitoring $false` re-enables, or a reboot clears the change. Tamper Protection (if enabled in Defender policy) blocks the call but the detection event still fires.
- **Persistence is multi-vector, lab-safe (steps 11-13).** Three persistence methods landed:
    - **User account** `phantomlab` — delete with `net user phantomlab /delete`
    - **Registry Run key** `HKCU:\...\Run\PhantomUpdater` — delete with `Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name PhantomUpdater`
    - **Scheduled task** `PhantomMaintenance` — delete with `schtasks /delete /tn PhantomMaintenance /f`

  Each one's payload is a no-op log append, not malicious code.
- **Security event log clear (step 20).** Genuinely deletes audit history. Security 1102 fires immediately as the next event. If you need pre-attack audit data preserved for forensics, run the chain on a host where the log was already exported or with a separate audit-log forwarder running. There is no way to suppress 1102 because Microsoft built it as the very next event written after a clear.

---

## Customizing for your lab

The two most operator-tunable values are hardcoded inline:

| Value | Where | Default | When to change |
|---|---|---|---|
| Victim IP | `lateral-smb-wmi-winrm.yml` + `bootstrap-win-host-01-attacker.yml` | `10.0.0.16` | If your victim agent is at a different internal IP |
| `phantomlab` password | `bootstrap-win-host-02-victim.yml` + `bootstrap-win-host-01-attacker.yml` + `lateral-smb-wmi-winrm.yml` + `create-phantomlab-user-localadmin.yml` | `PhantomLab2026X` | If your environment has stricter password policy. Must satisfy 3 of 4 complexity categories AND not contain the username `phantomlab`. Caldera stores the YAML verbatim so edits round-trip via export/import. |

To re-customize: edit the source YAML in `bundles/spark/caldera-content/`
and rebuild the phantom-caldera image. For a hot-fix without rebuilding,
**Advanced → Abilities → Import YAML** overwrites the loaded version by
UUID match.
