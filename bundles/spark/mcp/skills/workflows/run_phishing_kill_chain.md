---
name: run_phishing_kill_chain
displayName: Run phishing kill chain (Caldera)
category: workflows
description: 'Orchestrates the Phantom phishing → ransomware kill chain through Caldera — 20 atomic ATT&CK steps across two Windows agents (attacker + victim) with real cross-host SMB+WMI+WinRM lateral movement, LSASS dumping, Defender tampering, and event-log clearing tuned for noisy XDR telemetry. Verifies prereqs (both agents checked in, adversary auto-loaded from baked image), fires the operation, polls each step to completion, decodes per-step output, and produces a SOC-ready telemetry summary. Use when the operator wants to exercise their detection rules against a known-good attack baseline. Lab-safe — no actual encryption or real exfil.'
icon: target
source: platform
loadingMode: on-demand
locked: false
attack:
  - tactic: initial-access
    techniques: ["T1566.001"]
  - tactic: execution
    techniques: ["T1059.003"]
  - tactic: discovery
    techniques: ["T1087.001", "T1082", "T1018", "T1135"]
  - tactic: credential-access
    techniques: ["T1003.005", "T1003.001"]
  - tactic: privilege-escalation
    techniques: ["T1548.002"]
  - tactic: defense-evasion
    techniques: ["T1562.001", "T1140", "T1070.001"]
  - tactic: persistence
    techniques: ["T1136.001", "T1547.001", "T1053.005"]
  - tactic: lateral-movement
    techniques: ["T1021.002"]
  - tactic: collection
    techniques: ["T1119", "T1560"]
  - tactic: command-and-control
    techniques: ["T1071.004"]
  - tactic: exfiltration
    techniques: ["T1041"]
  - tactic: impact
    techniques: ["T1491"]
---

# Skill: Run phishing kill chain (Caldera)

## Category

workflows

## Purpose

Drive Caldera to execute the bundled `Phantom phishing → ransomware kill chain (cross-host, expanded)` adversary — a **20-step ATT&CK emulation** across two Windows agents that produces a controlled, reproducible telemetry baseline for SOC detection validation. Output: a per-step pass/fail summary + the cross-host lateral movement evidence (whose SMB session auths and WinRM remote command outputs prove that the move actually succeeded against the victim, not just that the attempt fired).

**Steps for richer XDR coverage:** discovery burst (T1082 + T1135 — `systeminfo`/`net share` LOLBin volume), **LSASS memory dump via `comsvcs.dll` (T1003.001 — the marquee EDR signal)**, Defender real-time tamper + exclusion (T1562.001), certutil `-decode` LOLBin (T1140), Registry Run key persistence (T1547.001), Scheduled task `/sc onlogon` persistence (T1053.005), and Security event log clear (T1070.001 — Security 1102 fires unconditionally).

**When to run:**
- Operator wants to validate detection rules against a known-good kill chain (rule authoring, tuning, regression test)
- After deploying new SIEM content (e.g. parsing rules, correlation searches) and you want a tested traffic source
- For training: a controllable walk-through of a phishing-to-ransomware sequence with clear per-step telemetry markers
- Before a customer demo where the SOC view needs to show "real attack indicators" — fire this, then walk the operator through the resulting events in `/observability/events` + their SIEM

**When NOT to run:**
- Production environment (this is a lab tool — even though it's lab-safe, it creates registry mutations, a local user, files in TEMP, AND clears the Security event log at step 20)
- Without two prepared Windows agents (the chain ASSUMES `group=red` and `group=victim` have one elevated sandcat each)
- When the bootstrap abilities haven't been run yet — the lateral step needs the workgroup-auth knobs set on the victim AND the attacker
- When the operator needs the pre-attack Security event log preserved (step 20 clears it — `wevtutil cl Security`)

## MITRE ATT&CK Tactics

11 tactics, 20 techniques. See the `attack:` frontmatter list for the full mapping.

## Prerequisites

Call these once before firing the chain. The skill checks them and aborts with a clear error message if anything's missing.

1. **Two Windows agents checked in** — one in `group=red` (attacker, IP typically 10.0.0.14), one in `group=victim` (target of lateral movement, typically 10.0.0.16). Both Elevated. Verify with `caldera_get_all_agents`; the response must list at least one agent per group.
2. **The adversary profile is auto-loaded** — by name `Phantom phishing -> ransomware kill chain (cross-host, expanded)` (or look up by ID `f81c14fe-6730-4215-bc95-e8eaca1530ab`). Verify with `caldera_get_adversary_by_name`; the response must show `atomic_ordering` with **20 ability UUIDs** **Auto-loaded from the baked phantom-caldera image** (`bundles/spark/caldera-content/` → overlaid into `/usr/src/app/data/{abilities,adversaries}/` at build time → Caldera's `data_svc.py` registers on container start). If absent, the caldera container might be running an older image — verify by running `docker inspect caldera --format '{{.Image}}'` and checking the digest against the release manifest.
3. **Both bootstrap abilities have been run** — `Bootstrap win-host-02 for lateral` on `group=victim`, AND `Bootstrap win-host-01 for lateral` on `group=red`. These are one-time setup that configures the workgroup-auth knobs (SMB firewall, WinRM TrustedHosts + AllowUnencrypted, phantomlab admin user, LocalAccountTokenFilterPolicy=1). Without them, the lateral step (step 14) generates the right telemetry but the SMB/WMI/WinRM sub-attempts fail auth.
   - **How to check**: this is harder to verify programmatically. Ask the operator: "Have you run the two bootstrap abilities on group=victim and group=red?" — if uncertain, suggest they run them as a one-shot operation each via the Caldera UI. The skill PROCEEDS even on negative answer, but warns the operator that lateral telemetry may not include successful cross-host execution evidence.

## Procedure

The agent runs these steps in order. Each step is a tool call (or a tight sequence of calls) — narrate progress to the operator between steps so they understand what's happening on the timer.

**XDR integration**: Steps D and H now invoke the `xdr_verify_simulation_telemetry` sub-skill to give the operator real-time + post-run confirmation that the SIEM (Cortex XDR) is seeing the simulation's telemetry. Both invocations are read-only and self-abort cleanly if the XDR connector isn't configured — they don't block the simulation.

### Known broken tools — do NOT call these

- **`caldera_get_operation_report`** — returns HTTP 405 against the current Caldera 5.3 API; the underlying endpoint changed in Caldera v2. Use `caldera_get_operation_by_id` for state + chain + result fields instead. Calling it only clutters the chat with noisy "method not allowed" errors.

### Step A — Verify agents + adversary

```
caldera_get_all_agents()                  # confirm 2 agents, 1 per group
caldera_get_adversary_by_name(
  name="Phantom phishing -> ransomware kill chain (cross-host, expanded)"
)                                          # confirm 20-step adversary present
```

Tell the operator the agent paws + IPs you see. If either prereq fails, STOP and tell the operator how to fix.

### Step B — Create the operation

```
op_start_epoch = int(time.time())  # capture for the XDR pulse window in Step D + sweep in Step H

caldera_create_operation(
  operation_name="phantom-killchain-{timestamp}",
  adversary_name="Phantom phishing -> ransomware kill chain (cross-host, expanded)"
)
```

Captures the returned `operation_id` AND `op_start_epoch`. The operation starts in `paused` state — Caldera's quirk. **Keep `op_start_epoch` in scope** for Steps D and H — it's the lower-bound timestamp for the XDR queries that bookend the operation. Capturing it BEFORE create_operation ensures the XDR query window covers the very first ability that fires (cmd dispatch can happen within seconds of state=running).

### Step C — Set the operation to target group=red + start it running

```
caldera_update_operation(
  operation_id=<from step B>,
  payload={
    "state": "running",
    "group": "red"
  }
)
```

`group=red` ensures the operation only targets the attacker (win-host-01). The lateral step in the chain itself reaches win-host-02 via SMB, so it doesn't need win-host-02 to be in the operation.

### Step D — Poll the operation to completion (with mid-chain XDR pulse)

**THIS STEP IS LONG-RUNNING — 10 to 14 MINUTES of wall-clock time. You MUST poll patiently; do NOT exit after a few polls. The agent must continue calling `caldera_get_operation_by_id` until the operation actually finishes, not until you think "enough polls have happened." This is the most common failure mode of running this skill — early exit while the chain is still executing.**

The Caldera agent beacons every 30-60 seconds. Each ability in the 20-step chain takes ~30-60s to dispatch + execute + report back. The full 20-step chain takes **10-14 minutes** of real time. There is no way to make this faster.

**Record `op_start_epoch`** as the moment immediately before `caldera_create_operation` in Step B. This is the lower bound for the XDR pulse query window.

#### The polling loop — strict invariants (use caldera_wait_for_operation_progress)

Use `caldera_wait_for_operation_progress` instead of bare `caldera_get_operation_by_id` polls. Each call blocks INSIDE the connector container for up to 90 seconds, returning as soon as Caldera's chain grows (a new ability fired) or the operation TRULY completes. ONE call = ~30-60s of wall-clock progress = 1-2 abilities completed. The 20-step chain finishes in ~10-20 calls (chain has 20 abilities × N agents = 40 entries when 2 agents in group=red).

**`state=paused` is not terminal**: Caldera's atomic planner uses `paused` BETWEEN ability dispatches — not just at end of operation. Exiting the polling loop on `paused` stops while Caldera is still firing abilities. The wait tool distinguishes paused-mid-run from end-of-operation via the `expected_total_abilities` parameter.

#### Call pattern (compact response)

**The wait tool returns a COMPACT summary instead of the full 50KB Caldera blob**, which a model can misread (for example hallucinating `last_chain_length=40` after seeing chain=2 entries). The compact response has explicit `done` flag, numeric progress, and ready-to-copy `next_call_args`. The agent loop becomes mechanical:

```
# How many chain entries indicate "done"? Caldera fires each ability on each
# in-scope agent: total = 20 abilities × #agents in group=red. Typically 40.
expected_total = 20 * count_of_red_group_agents

result = caldera_wait_for_operation_progress(
  id=<op_id>,
  last_chain_length=0,
  expected_total_abilities=expected_total,
  timeout_seconds=90,
)

while not result["done"]:
    # The compact response gives you the progress signal directly:
    p = result["chain_progress"]
    state = result["state"]
    recent = result["recent_abilities"]  # last 3 by name

    # Narrate ONE LINE — pull from the compact numbers, NOT a 50KB blob
    print(f"Caldera: state={state}, {p['completed_terminal']}/{p['expected_total']} "
          f"done, {p['in_flight']} in-flight, recent: {[r['name'] for r in recent]}")

    # Every other turn: XDR pulse using op_start_epoch in ms
    if turn_counter % 2 == 0:
        xdr_get_cases_and_issues(from_time=<op_start_epoch_in_ms>, limit=10)

    # Continue the loop. The tool returns next_call_args ready to use.
    result = caldera_wait_for_operation_progress(**result["next_call_args"])

# Loop exited because result["done"] is True. That means EITHER:
#   - chain has expected_total entries AND all entries are in terminal status, OR
#   - state shifted to finished/cleanup/out_of_time
```

#### Critical: trust the `done` flag, not your own counting

**The connector pre-computes `done` for you.** The connector knows:
- Caldera's `state=paused` is NOT terminal (atomic planner uses it between abilities)
- Caldera's `state=running` may persist forever (auto_close=false), so don't wait for state to flip
- `chain.length=40` doesn't mean "all 40 abilities executed" — Caldera queues all links upfront with status=-3. The connector verifies ALL chain entries have status in {0, 1, -2, -4, -5} before declaring done.

If `result["done"]` is False, CALL THE TOOL AGAIN. Don't try to determine doneness from your own reading of `chain_progress` — the connector does the math correctly, you might miss a subtlety (e.g. chain=40 but all status=-3 pending → not done; only the connector knows that).

#### Why `expected_total = 20 × N_agents`

Caldera's atomic planner fires each ability on EACH in-scope agent. With 2 agents in group=red, ability A1 fires on win-host-01 AND win-host-02 → 2 chain entries for that one ability. So a 20-step adversary on 2 agents = 40 chain entries when complete. **Always count your agents first** via `caldera_get_all_agents` filtered to `group=red`. Setting `expected_total_abilities=20` when 2 agents are in scope would cause early-exit (chain hits 20 when ability 10 fires on both agents).

#### Why the LLM tends to give up early (LLM-author note to self)

When you (the agent) read this skill, your natural instinct after a few tool calls is to "synthesize" a response. Resist that instinct here. With the wait tool, each call takes ~30-60s of real time and IS productive — it's not a no-op poll. **The natural pattern for this step is 10-15 sequential `caldera_wait_for_operation_progress` calls, with brief one-line progress narration between them — NOT 3 calls followed by a written summary.** If you find yourself wanting to wrap up before the chain has 20 entries, that's the early-exit failure pattern; the wait tool exists specifically to make this loop short enough that you can complete it within max_turns.

#### Fallback (only if the wait tool is unavailable)

If the `caldera_wait_for_operation_progress` tool isn't available (older connector image), fall back to bare `caldera_get_operation_by_id` polls with a longer cadence. But: this consumes max_turns rapidly. Strongly prefer the wait tool.

#### Mid-chain XDR pulse

After the FIRST 60 seconds have elapsed (i.e. you've done 2-3 polls), invoke the `xdr_verify_simulation_telemetry` sub-skill every other poll (~60s cadence) in **pulse** mode. The pulse is read-only + non-blocking — if XDR connector is unavailable, the pulse self-aborts cleanly and the simulation continues.

The pulse-mode invocation expects:

```
op_start_epoch       = <captured timestamp> (string of digits OR ISO; sub-skill accepts either)
affected_hosts       = ["win-host-01", "win-host-02"]
expected_techniques  = ["T1566.001", "T1059.003", "T1059.001",
                        "T1087.001", "T1082", "T1018", "T1135",
                        "T1003.005", "T1003.001",
                        "T1548.002",
                        "T1562.001", "T1140", "T1070.001",
                        "T1136.001", "T1547.001", "T1053.005",
                        "T1021.002",
                        "T1119", "T1560",
                        "T1071.004",
                        "T1041",
                        "T1491"]
mode                 = "pulse"
```

The pulse output is a one-line `🛰️ XDR pulse @ Mmin Xs: N new incident(s)...` line. Insert it inline in your narrative between polls. **Don't block on it; immediately resume polling Caldera.**

#### Calling xdr_get_cases_and_issues directly (alternative)

If the sub-skill abstraction is hard to follow within a single chat turn, you may call `xdr_get_cases_and_issues` directly with:

```
xdr_get_cases_and_issues(from_time="<op_start_epoch_in_ms>", limit=20)
```

The `from_time` parameter accepts both ISO strings AND numeric epoch (string or int). The tool defaults to filtering on `modification_time` (NOT `creation_time`) — that's the right semantic for kill-chain verification because XDR clusters new alerts into EXISTING cases by threat fingerprint. A case from a previous run that's still being updated by your current run shows up in the filtered list. NO client-side filtering needed; the connector does it server-side with the correct semantic.

#### Poll cadence

- Don't poll faster than every 25 seconds — Caldera's API throttles + each poll returns large objects.
- Don't pause longer than 60 seconds between polls — the operator wants progress feedback.
- 30-second cadence is the sweet spot.

#### What "the operation is done" actually looks like

The poll response will eventually return JSON with these markers:

```json
{
  "state": "finished",
  "chain": [
    { "status": 0, "ability": {"name": "Phishing emailclient.exe spawn"}, ... },
    { "status": 0, "ability": {"name": "Cmd drops + runs script"}, ... },
    ...
    // 20 entries total
  ]
}
```

When you see all three (state=finished, chain length 20, every status in {0,1,-2}), and ONLY then, move on to Step E.

#### Avoiding context-window bloat during the poll loop

Each `caldera_get_operation_by_id` response is large (~50KB raw, includes the entire chain[] with full ability metadata + facts + relationships). 20-30 polls × 50KB = 1-1.5MB of tool-result content in the chat context. Gemini 2.5 Pro / 3.0 Pro have 1M-2M token windows but you still want to be efficient. **Between polls, summarize the result in 1-2 lines max** (`state=running, 7/20 done, last ability: T1559 lateral`). DO NOT dump the full poll response into your narration.

#### XDR pulse summary at end of poll loop

When the conditions above are met (state=finished etc.), emit one final pulse-mode XDR check before moving to Step E. This is the "as the chain ends" snapshot — useful for the gap analysis in Step H to know which XDR rules fired by completion time.

**The XDR pulse is parallel evidence, not authoritative**. Caldera links going to status=0/1 is the simulation's "this step fired." The XDR pulse is the SIEM's "yes I saw it." Report both to the operator so they know which side is the bottleneck if any single technique doesn't appear.

### Step E — Per-step decode

For each ability in the chain's atomic_ordering, fetch the link result + decode the output. Pay special attention to the **headline detection steps**:

- **Step 7 — LSASS minidump (T1003.001)**. Stdout shows `lsass.exe PID: NNNN` and either `[+] Dump file created: ... (N bytes)` (success) or `[!] Dump file NOT created -- Defender ... blocked it` (success-from-detection-perspective: rundll32 attempted the handle to lsass.exe; Sysmon EID 10 fires either way).
- **Step 9 — Defender real-time disable (T1562.001)**. Stdout shows `Defender state BEFORE` then either `[+] Set-MpPreference ... succeeded` or `[!] Set-MpPreference failed: ... Tamper Protection enabled`. The failure path is detection-equivalent — the attempt itself fires the Defender-Operational 5001 event.
- **Step 14 — Lateral to win-host-02**. Stdout shows:
    - `Port scan: SMB(445)=True WinRM(5985)=True` if both ports are reachable
    - `SMB admin share mapped: Z: -> \\10.0.0.16\C$` on successful auth
    - `WMI remote query SUCCEEDED on 10.0.0.16` with OS info from win-host-02
    - `WinRM Invoke-Command SUCCEEDED on 10.0.0.16: Host: win-host-02 User: win-host-02\phantomlab` — proof of remote code execution
- **Step 20 — Clear Security event log (T1070.001)**. Stdout shows the BEFORE/AFTER record counts (typically 10000+ → 1) and `wevtutil cl Security exited 0`. The Security 1102 event fires as the very next event — confirm this on the host via Event Viewer.

```
for each link in operation.chain:
  caldera_get_operation_link_result(
    operation_id=<op_id>,
    link_id=link.id
  )
  # Decode base64 result → JSON → stdout/stderr/exit_code
```

### Step F — Telemetry summary for the operator

Produce a markdown table summarizing the 20 steps + the lateral evidence. Format:

```
| # | Tactic | Step | Status | Highlight |
|---|---|---|---|---|
| 1 | initial-access | Phishing emailclient.exe spawn | ✅ | PID=NNNN, attachment dropped at TEMP |
| 2 | execution | Cmd drops + runs script | ✅ | … |
| 7 | credential-access | LSASS minidump via comsvcs.dll | ✅ | rundll32 → lsass.exe handle (Sysmon EID 10) |
| 9 | defense-evasion | Defender real-time disable | ✅ | 5001/5007 events in Defender-Operational |
| 14 | lateral-movement | Lateral to win-host-02 | ✅ | Remote hostname=win-host-02 returned via WinRM |
| 20 | defense-evasion | Clear Security event log | ✅ | Security 1102 fired (1 → ∞ records cleared) |
```

**For step 14 specifically (the lateral)**, extract from the decoded stdout:
- The remote hostname / user returned from WinRM (proves real RCE on win-host-02)
- The OS Caption / version returned from WMI (proves real cross-host WMI)
- The marker filename dropped via SMB (proves real cross-host file write)

### Step G — Status=1 false-positive call-out

Caldera marks abilities `status=1` when its built-in fact parser can't find expected facts in the output. Specifically, **steps 8 (Fodhelper UAC bypass) and 11 (Create local user — stockpile)** routinely show `status=1` even though the underlying command succeeded — the registry key gets created, the user gets created, the telemetry fires correctly. Tell the operator explicitly:

> "Steps 8 and 11 may show ❌ in Caldera but the telemetry on the host fired correctly — these are parser false negatives, not real failures. Verify by checking event log on win-host-01 for Security 4720 (account create) and Sysmon EID 13 (registry value set on `HKCU\software\classes\ms-settings\shell\open\command`)."

Also explain the **expected-failure** signals on Defender-enabled hosts:
- **Step 7 LSASS dump** — may show `[!] Dump file NOT created -- Defender blocked it` in stdout. This is **success from a detection standpoint** — rundll32 attempted the handle to lsass.exe and the EDR caught it. The Sysmon EID 10 (process access) event fired.
- **Step 9 Defender disable** — may show `[!] Set-MpPreference failed: ... Tamper Protection enabled`. Again **success from a detection standpoint** — the Set-MpPreference call itself triggers Defender's own 5001 event.

### Step H — Final XDR sweep + detection-coverage gap analysis

After the kill chain completes and the per-step summary is rendered (Step F), do a deeper XDR pull to give the operator the **detection-side picture**, including a per-technique gap analysis. This is the bookend to the Step D mid-chain pulses.

Invoke the `xdr_verify_simulation_telemetry` skill in **sweep mode**:

```
invoke xdr_verify_simulation_telemetry skill with:
  op_start_epoch = <captured in Step B>
  affected_hosts = ["win-host-01", "win-host-02"]
  expected_techniques = [
    "T1566.001", "T1059.003", "T1059.001",
    "T1087.001", "T1082", "T1018", "T1135",
    "T1003.005", "T1003.001",
    "T1548.002",
    "T1562.001", "T1140", "T1070.001",
    "T1136.001", "T1547.001", "T1053.005",
    "T1021.002",
    "T1119", "T1560",
    "T1071.004",
    "T1041",
    "T1491",
  ]
  mode = "sweep"
```

The sub-skill produces:
- Markdown table of all incidents created since `op_start_epoch`
- Per-technique gap analysis (which expected techniques fired in XDR, which didn't)
- Action recommendations for gaps (likely missing detection rules or filter mismatches)

**If the XDR connector is unavailable** (no instance configured, instance unhealthy, or `xdr_get_cases_and_issues` returned an error in Step 1 of the sub-skill), the sweep self-aborts cleanly with a single line: *"XDR sweep skipped — connector not ready. Configure /connectors → cortex-xdr to see detection coverage analysis on the next run."* The kill-chain itself is still considered complete — the XDR step is an add-on, not load-bearing.

**Concretely report to the operator at the end of Step H**:
1. The full XDR sweep output (delegated to the sub-skill)
2. A one-line recap: *"Caldera fired N/20 steps successfully; XDR observed M incidents covering K of the 22 expected techniques. Gaps: <comma-separated technique list>."*
3. Pointer for follow-up: *"Open `/observability/detections` to browse XDR's full rule inventory and see which rules fired during this run. /observability/events shows the Phantom audit trail for the Caldera tool calls."*

## Forbidden — what this skill must NOT do

- **Never invoke the bootstrap abilities automatically.** They modify host security state (firewall + WinRM + LocalAccountTokenFilterPolicy + creating a local admin). Operator must consciously authorize this — surface the requirement in the prereq check and let them run the bootstraps via the Caldera UI as a separate one-shot operation.
- **Never create or modify the adversary profile itself.** The YAMLs ship baked into the phantom-caldera image (`bundles/spark/caldera-content/` overlaid to `/usr/src/app/data/{abilities,adversaries}/` at build time), so a fresh install has them out-of-the-box. If they're missing, the operator is on an older caldera image — tell them to upgrade, not to manually import. Don't auto-import — that risks duplicate IDs and breaks the operator's expected configuration management.
- **Never delete the marker artifacts left on win-host-02 after the lateral step.** They're evidence — the operator should be able to RDP in and see `C:\Windows\Temp\lateral_v6_marker_*.txt` as proof. Cleanup happens at operation tear-down via Caldera's own cleanup mechanism if the abilities declare one.
- **Never fire this chain without operator confirmation.** It creates real registry mutations + a local user + scheduled task + Run key on the host AND clears the Security event log at step 20. Even though it's lab-safe, the operator must explicitly approve "yes, run the expanded kill chain now."
- **Never claim the kill chain succeeded when steps 8 or 11 show status=1 without explanation.** Always note these are parser false-negatives and tell the operator how to verify in Event Viewer.
- **Never re-enable Defender or reverse the Defender disable automatically.** That's the operator's call — the disabled state is itself part of the detection scenario (operators may want their SIEM to alert on the state mismatch over time).
- **Never let the XDR pulse (Step D) or sweep (Step H) block the kill chain itself.** The XDR sub-skill is read-only + best-effort; if it errors, log a one-line warning and continue the Caldera polling loop. Caldera-side success is the load-bearing signal; XDR-side confirmation is the bonus detection-coverage check.
- **Never modify XDR state from this skill.** No closing cases, no acknowledging issues, no rule edits. The sub-skill enforces this; this skill must not bypass.

## Cleanup

The expanded kill chain leaves multiple durable artefacts on the hosts:
1. **win-host-01**: an `emailclient.exe` (renamed notepad copy) in `C:\Users\<user>\AppData\Local\Temp\PhantomLab\` + the `T1136.001_PowerShell` user account from step 11 + the Fodhelper UAC bypass registry key under HKCU + the `PhantomUpdater` registry Run-key value + the `PhantomMaintenance` scheduled task + Defender real-time monitoring disabled + three Defender exclusion paths + (if successful) an empty Security event log (cleared at step 20).
2. **win-host-02**: the `phantomlab` admin user (created by bootstrap, persists) + the lateral marker file under `C:\Windows\Temp\lateral_v6_marker_*.txt`.
3. **Caldera**: the operation record itself (with chain history + decoded outputs).

For a clean re-run, tell the operator they can either:
- Leave artefacts in place — re-runs are idempotent for most abilities; persistence + Defender mods don't auto-undo, so they accumulate
- Manually clean (on win-host-01, elevated PowerShell):
  ```powershell
  # Persistence cleanup
  net user T1136.001_PowerShell /delete
  net user phantomlab /delete
  Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name PhantomUpdater
  schtasks /delete /tn PhantomMaintenance /f
  # Defender restore
  Set-MpPreference -DisableRealtimeMonitoring $false
  Remove-MpPreference -ExclusionPath "C:\Windows\Temp"
  Remove-MpPreference -ExclusionPath "C:\Users\Public"
  Remove-MpPreference -ExclusionPath "C:\PerfLogs"
  # File cleanup
  Remove-Item C:\Users\$env:USERNAME\AppData\Local\Temp\PhantomLab\* -Recurse -Force
  # (Security event log is naturally repopulated as the OS runs)
  ```

## Variations

If the operator wants to vary the chain:
- **Single-host telemetry** (no cross-host): tell them to use a single-host kill chain instead — same non-lateral steps fire on win-host-01 only. To configure: ask the operator to clone the adversary in the Caldera UI and remove the step-14 lateral ability.
- **Different victim IP**: the lateral ability hardcodes `10.0.0.16`. If the operator's victim has a different IP, they need to edit the source YAML (`bundles/spark/caldera-content/abilities/07-lateral-movement/lateral-smb-wmi-winrm.yml`) and rebuild the phantom-caldera image OR import the modified YAML into the running Caldera via the UI. The skill cannot do this rewrite — operator action only.
- **Skip the noisy steps**: if operator wants the shorter 12-step chain (no LSASS, no Defender tamper, no event-log clear, just the original 12 steps), tell them to clone the adversary in the Caldera UI and remove the new ability UUIDs (4-5, 7, 9-10, 12-13, 20 in the 20-step ordering).
- **Re-run only step N**: tell the operator to use the Caldera UI's "Manual Command" feature on a paused or finished operation to fire individual abilities.

## Telemetry signatures (operator handoff)

After the chain completes, the operator should validate the following event signatures in their SIEM. The skill should output this table verbatim so the operator has a checklist.

| Step | Event source | Signature |
|---|---|---|
| 1 | Sysmon EID 1 | `Image` ends in `emailclient.exe`, `OriginalFileName=NOTEPAD.EXE` (masquerade T1036.005) |
| 2 | Sysmon EID 1 + 11 | `cmd.exe` writes a `.bat`/`.cmd`/`.ps1` then runs it from `%TEMP%` |
| 3 | Sysmon EID 1 | Burst of `whoami` / `Get-LocalUser` / `query session` processes |
| **4** | **Sysmon EID 1 (4-LOLBin burst)** | **`systeminfo`, `arp`, `netstat`, `route` within 5s window — high-confidence discovery burst** |
| **5** | **Sysmon EID 1 + Microsoft-Windows-SMBClient EID 30622** | **`net share`, `net view`, `Get-SmbShare` — share enum** |
| 6 | Sysmon EID 1 | `cmdkey.exe` execution (rare in benign workflows) |
| **7** | **Sysmon EID 10 + EID 11** | **`rundll32.exe` opens handle to `lsass.exe` then writes `.dmp` to TEMP — marquee EDR rule** |
| 8 | Sysmon EID 13 | Registry value set at `HKCU\software\classes\ms-settings\shell\open\command\` |
| **9** | **Microsoft-Windows-Windows Defender/Operational 5001 + 5007** | **Defender real-time monitoring disabled + exclusion path added** |
| **10** | **Sysmon EID 1 + 11** | **`certutil.exe -decode` with file output to TEMP — LOLBin abuse** |
| 11 | Security 4720 | New local account `T1136.001_PowerShell` created |
| **12** | **Sysmon EID 13** | **Registry value SET under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\PhantomUpdater`** |
| **13** | **Security 4698 + TaskScheduler/Operational 106** | **Scheduled task `PhantomMaintenance` created with `/sc onlogon /ru SYSTEM /rl HIGHEST`** |
| 14 | Sysmon EID 3 + Security 4624/4672 on win-host-02 | Outbound TCP 445 + 5985 from win-host-01 → 10.0.0.16, followed by NTLM auth on win-host-02 as `phantomlab`, then remote process creation |
| 15 | Sysmon EID 11 | High-volume file enumeration in user-home dirs |
| 16 | Sysmon EID 1 + 11 | `Compress-Archive` produces `.zip` in TEMP |
| 17 | Sysmon EID 22 | 10 distinct DNS queries to subdomains of `phantomlab.example.invalid` |
| 18 | Sysmon EID 3 | Outbound HTTP POST with base64 body to `10.0.0.81:8888` |
| 19 | Sysmon EID 11 | `.txt` file create in user-visible directory with "ransom"-style naming |
| **20** | **Security 1102** | **Security event log cleared via `wevtutil cl Security` — fires UNCONDITIONALLY (Microsoft built it specifically to flag this — cannot be suppressed)** |

Tell the operator: "Open `/observability/events` after the operation finishes — events from the agent appear there (audit). For Windows-side telemetry, RDP into win-host-01 + `eventvwr.msc` → filter Security log for Event IDs 4688/4720/4698/1102 and Sysmon logs for the EIDs above. Defender events live in `Microsoft-Windows-Windows Defender/Operational`."
