---
name: xdr_verify_simulation_telemetry
displayName: Verify XDR telemetry for a simulation (Cortex XDR)
category: workflows
description: 'After firing a Phantom simulation (kill chain, scenario worker, or single-technique replay), search the connected Cortex XDR instance for cases and issues that were triggered by the simulation activity. Reports a time-bounded list of new incidents created since the operation started, cross-references them against the simulation steps where possible, and gives the operator an at-a-glance confirmation that XDR is seeing the telemetry. Designed to be invokable either standalone ("did my last test show up in XDR?") OR as a sub-step of an orchestration skill like run_phishing_kill_chain. Lab-safe — read-only queries against XDR; no incident state mutation.'
icon: radar
source: platform
loadingMode: on-demand
locked: false
attack: []
---

# Skill: Verify XDR telemetry for a simulation

## Category

workflows

## Purpose

Close the loop between **a simulation that fires** (Caldera kill chain, xlog scenario worker, single-technique replay) **and the SIEM that should detect it** by querying Cortex XDR's incident store for cases + issues that landed during/after the operation's time window. The output answers two questions for the operator:

1. **Did XDR see the activity?** — count of incidents/issues created since the simulation's start time, listed with severity + affected hosts + detection rule names
2. **Which simulation step likely triggered each?** — best-effort cross-reference: incident timestamps vs simulation step timestamps, plus host-of-record matching

**When to run:**
- As a sub-step inside a simulation orchestration skill (e.g. mid-chain XDR pulse during `run_phishing_kill_chain`, or final-sweep after the chain completes)
- Standalone, after the operator manually ran a Caldera operation or scenario worker, to confirm telemetry made it to XDR
- During detection-rule tuning: fire a known-good simulation, query XDR with this skill, confirm the rule you authored is in the returned list
- For demo prep: show the operator that simulation → XDR is wired and producing real incidents

**When NOT to run:**
- Without a configured cortex-xdr connector instance (the skill will detect this and fail-loudly with a clear "configure /connectors → cortex-xdr first" message; don't blindly retry)
- Right at simulation start (XDR detection rules can take 30s-5min to fire after the underlying telemetry lands; querying immediately means an empty result that's not yet a real signal). Use the agent's polling pattern with at least 60s between queries.
- For non-XDR SIEMs (Splunk, Sentinel, etc.) — this skill is XDR-specific. Different SIEM = different connector + different skill.

## Tools used

The cortex-xdr connector (registered via the Cortex XDR connector instance) exposes:

- **`xdr_get_cases_and_issues`** — primary tool. Returns the list of XDR cases (a.k.a. incidents in the XDR API) and per-case issues (a.k.a. alerts). Defaults to filtering on `modification_time` (NOT `creation_time`) because XDR clusters new alerts into existing cases by threat fingerprint — a case created yesterday can receive new alerts today, and `creation_time` would miss those entirely. Pass `time_field="creation_time"` only if you specifically want a "brand-new cases today" view.
- **`xdr_get_incident_extra_data`** — drill-down. Given an incident ID, returns the full alert/issue list with rule names, hosts, MITRE technique IDs.
- **`xdr_run_xql_query`** — for arbitrary XQL. Start a query; returns a `query_id`. Heavy/expensive; use sparingly and only when `get_cases_and_issues` doesn't surface what you need.
- **`xdr_get_xql_results`** — poll for results of a previously-started XQL query.

## Inputs (caller-supplied)

When invoked from an orchestration skill, the parent skill should pass:

| Field | Type | Purpose |
|---|---|---|
| `op_start_epoch` | int (epoch seconds) | Filter incidents to those created at or after this moment. For Caldera kill chains, this is the timestamp captured when `caldera_create_operation` returned. |
| `affected_hosts` | list[str], optional | Hostnames the simulation targets. Used to cross-reference incidents' affected-host list. Example: `["win-host-01", "win-host-02"]` for the run_phishing_kill_chain. |
| `expected_techniques` | list[str], optional | MITRE T-codes the simulation expected to fire (e.g. `["T1003.001", "T1562.001"]`). Used to flag incidents whose mapped techniques match — these are high-confidence simulation matches. |
| `mode` | "pulse" or "sweep" | `pulse` = quick check during the simulation, report counts and top-3 incidents only; `sweep` = final exhaustive check after simulation completes, report all incidents with full detail. |

If the caller is the operator directly (standalone invocation), infer:
- `op_start_epoch` = the timestamp 10 minutes ago, OR ask the operator "when did your simulation start?"
- `affected_hosts` = none; just report everything
- `expected_techniques` = none; just report everything
- `mode` = "sweep"

## Procedure

### Step 1 — Verify cortex-xdr connector is ready

Before any XDR query, confirm the connector is reachable:

```
# Look at the connectors list — cortex-xdr should be present + state "connected"
# Use /api/agent/connectors via the agent's instance_list tool or fall back
# to a single xdr_get_cases_and_issues with limit=1 as a connectivity probe.
xdr_get_cases_and_issues(limit=1)
```

If this returns an `ConnectorProxyError` or `no apiKey configured`:
- **STOP.** Tell the operator: *"The cortex-xdr connector isn't reachable. Go to /connectors → cortex-xdr → verify the instance exists with the right api_url + api_id + api_key. If the instance is healthy, try /connectors → cortex-xdr → Test Connection."*
- Do NOT retry blindly. Do NOT proceed with the rest of the skill. The orchestration skill should record this as a non-fatal warning ("XDR check skipped — connector not ready") and continue with the simulation.

If the probe returns `{"ok": true, "incidents": [...]}` (or similar), proceed to Step 2.

### Step 2 — Fetch incidents touched since op_start_epoch

```
# Pass from_time directly. The connector defaults to modification_time
# filtering, which is the RIGHT semantic for simulation verification:
# XDR clusters new alerts into existing cases by threat fingerprint, so the
# same case can receive a fresh alert from your kill chain even if XDR
# created the case days ago. Filtering on creation_time would silently
# miss updates to older cases.
result = xdr_get_cases_and_issues(
  from_time=str(op_start_epoch * 1000),  # epoch ms; numeric-string is fine
  limit=200,
  # time_field="modification_time" is implicit default; only pass
  # time_field="creation_time" if you specifically want net-new cases.
)
```

The connector returns incidents already filtered + sorted by `modification_time` DESC. No client-side time filtering needed; just consume the list.

If `affected_hosts` was passed: filter client-side to incidents whose `hosts` array intersects with it (the connector currently doesn't expose host filtering on this tool).

Capture: `new_incident_count = len(result["incidents"])`, `top_3 = result["incidents"][:3]`.

### Step 3a — "pulse" mode reporting (mid-simulation)

If `mode == "pulse"`, output ONE concise line + bullets:

```
🛰️ XDR pulse @ <elapsed minutes>:<seconds> into simulation:
  • <N> new incident(s) since op start ({op_start_epoch})
  • Top: <severity emoji> <rule_name> on <host> — <relative time>
  • Top: <severity emoji> <rule_name> on <host> — <relative time>
  • Top: <severity emoji> <rule_name> on <host> — <relative time>
  (use 🔴 for high/critical, 🟠 for medium, 🟡 for low, ⚪️ for unknown)
```

If `new_incident_count == 0`:

```
🛰️ XDR pulse @ <elapsed>: no incidents yet. XDR rules can take 30s-5min to fire after the underlying telemetry lands; this is normal. The orchestrator will pulse again in ~60s.
```

DO NOT block the orchestration. Return immediately and let the orchestrator continue polling the simulation.

### Step 3b — "sweep" mode reporting (post-simulation)

If `mode == "sweep"`, do the deeper drill-down. For each filtered incident (up to 20):

1. Call `xdr_get_incident_extra_data(incident_id=<id>)` to get the full issue/alert list
2. Extract: `rule_name`, `severity`, `category`, `mitre_technique_id`, `description`, `host`
3. If `expected_techniques` was passed and `mitre_technique_id` matches, flag the incident with ⭐ (high-confidence simulation match)
4. Group incidents by host

Produce a markdown summary:

```
## 🛰️ XDR sweep — telemetry observed

**Time window**: <op_start_epoch human-readable> → now (elapsed <X> minutes)
**Affected hosts probed**: <list>
**Expected techniques**: <list>

**Incident count**: <N total>
- ⭐ <K> match expected MITRE techniques (high-confidence simulation matches)
- 🔴 <H> high/critical
- 🟠 <M> medium
- 🟡 <L> low

| ⭐ | Severity | Rule | Host | Technique | Created (relative) |
|---|---|---|---|---|---|
| ⭐ | 🔴 | LSASS memory access by rundll32.exe | win-host-01 | T1003.001 | -2min |
| ⭐ | 🟠 | Defender real-time monitoring disabled | win-host-01 | T1562.001 | -3min |
| | 🟠 | Suspicious scheduled task created | win-host-01 | T1053.005 | -1min |
| | 🟡 | New local user account | win-host-01 | T1136.001 | -4min |
...

**XQL drilldown** (if the operator wants more): the relevant XQL would be:
\`\`\`
dataset=xdr_data | filter agent_hostname in ("win-host-01", "win-host-02")
                 | filter _time > <op_start_epoch_iso>
                 | comp count() by event_type, agent_hostname
\`\`\`
```

### Step 4 — Cross-reference (sweep mode only)

If both `expected_techniques` and `affected_hosts` were passed, produce a **gap analysis**:

```
**Detection coverage gap analysis**:

| Expected technique | XDR incident? | Notes |
|---|---|---|
| T1003.001 (LSASS dump) | ✅ Rule "LSASS access by rundll32" | matched |
| T1562.001 (Defender disable) | ✅ Rule "Defender RT off" | matched |
| T1547.001 (Run key persistence) | ❌ NONE | Check if XDR rule exists; if so check the rule's filter — may not match this specific registry path |
| T1070.001 (Security log clear) | ✅ Rule "Security event log cleared (1102)" | matched |
```

Each ❌ row is a real signal — the operator should review whether their XDR content has coverage for that technique.

### Step 5 — Output to operator

Print the result with clear visual hierarchy. Use markdown headers so the operator can skim. End with a short call-to-action:

- **All techniques matched**: *"XDR coverage validated for this simulation. Operator can now move on to detection-rule tuning or run a different scenario."*
- **Some gaps**: *"N gap(s) flagged above. Worth reviewing your XDR content against these technique IDs — either a missing rule, or the rule exists but its filter doesn't match this simulation's exact event shape."*

## Forbidden — what this skill must NOT do

- **Never modify XDR state** — no closing incidents, no acknowledging cases, no commenting on cases. This skill is read-only. If the operator wants to triage, they go to the XDR UI themselves.
- **Never invent incidents.** If `xdr_get_cases_and_issues` returns 0 incidents, report 0. Don't pad the response with imagined matches.
- **Never claim a definite causation between simulation step N and incident I without timestamp + host + technique evidence.** The cross-reference is best-effort, not authoritative. Use phrases like *"likely triggered by step N"* not *"caused by step N"* unless all three signals agree.
- **Never query XQL when `xdr_get_cases_and_issues` would suffice.** XQL is heavyweight + costs the operator XSIAM compute budget. Reserve XQL for cases where the incident store doesn't have the data you need (typically rare in a kill-chain check).
- **Never sleep > 5s in a single tool call.** XDR API call timeouts are connector-side; the agent should NOT also delay. For polling, the parent orchestration skill manages the loop cadence.
- **Never proceed if Step 1's connector probe fails.** A "connector not ready" early-exit is the right answer; not pretending the data is there.

## Output examples

### Example: pulse mode, mid-kill-chain, incidents are starting to land

```
🛰️ XDR pulse @ 4min 30s into simulation:
  • 3 new incident(s) since op start (<op start, ISO 8601>)
  • Top: 🔴 LSASS memory access via rundll32 on win-host-01 — -1m ago
  • Top: 🟠 Defender real-time monitoring disabled on win-host-01 — -2m ago
  • Top: 🟡 New local account "T1136.001_PowerShell" created on win-host-01 — -3m ago
```

### Example: pulse mode, no incidents yet (very early in chain)

```
🛰️ XDR pulse @ 1min into simulation: no incidents yet. XDR rules can take 30s-5min to fire after the underlying telemetry lands; this is normal. Continuing simulation; will pulse again in ~60s.
```

### Example: sweep mode, kill-chain finished, gap analysis included

```
## 🛰️ XDR sweep — telemetry observed

**Time window**: <op start, ISO 8601> → now (elapsed 14 minutes)
**Affected hosts probed**: win-host-01, win-host-02
**Expected techniques**: T1003.001, T1562.001, T1547.001, T1070.001, T1136.001, T1059.003, T1059.001

**Incident count**: 8 total
- ⭐ 5 match expected MITRE techniques (high-confidence simulation matches)
- 🔴 2 high/critical
- 🟠 4 medium
- 🟡 2 low

| ⭐ | Severity | Rule | Host | Technique | Created |
|---|---|---|---|---|---|
| ⭐ | 🔴 | LSASS access by rundll32.exe | win-host-01 | T1003.001 | -12m |
| ⭐ | 🟠 | Defender RT monitoring disabled | win-host-01 | T1562.001 | -10m |
| ⭐ | 🟠 | Security event log cleared (1102) | win-host-01 | T1070.001 | -1m |
| ⭐ | 🟡 | New local account created | win-host-01 | T1136.001 | -7m |
| ⭐ | 🟠 | LOLBin: certutil -decode | win-host-01 | T1140 | -9m |
|  | 🔴 | Suspicious WinRM remote command | win-host-02 | T1021.006 | -6m |
|  | 🟡 | Scheduled task created | win-host-01 | (uncategorized) | -8m |

**Detection coverage gap analysis**:

| Expected technique | XDR incident? | Notes |
|---|---|---|
| T1003.001 (LSASS dump) | ✅ matched | |
| T1562.001 (Defender disable) | ✅ matched | |
| T1547.001 (Run key persistence) | ❌ NONE | Worth reviewing — does your XDR ruleset cover Registry Run key writes? |
| T1070.001 (Security log clear) | ✅ matched | |
| T1136.001 (Account create) | ✅ matched | |
| T1059.003 (Cmd execution) | ❌ NONE | Likely too noisy in your env to have a dedicated rule — common workaround. |
| T1059.001 (PowerShell) | ❌ NONE | Same as above. |

**Action**: T1547.001 (Run key persistence) is a high-signal technique that's typically caught by XDR's "Persistence via Run keys" alert. If your tenant has that rule, check its filter — this simulation set the value via HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\PhantomUpdater; if your rule filters on HKLM only, that's the gap.

XDR coverage validated for 5 of 7 expected techniques. T1547.001 is the most actionable gap — recommend the operator review their XDR content.
```

## Standalone-invocation prompts

Operators may invoke this skill directly with prompts like:

- *"Did my last kill chain show up in XDR?"* — skill infers op_start = 15min ago, affected_hosts = none, mode = sweep
- *"Check XDR for incidents from the last hour"* — same, broader window
- *"What did XDR see in the last 5 minutes?"* — narrower window, pulse mode
- *"Is XDR catching the LSASS dump I just fired?"* — narrow window, expected_techniques = ["T1003.001"]

Handle these by adjusting `op_start_epoch` + `mode` based on the operator's phrasing. If the prompt is ambiguous ("did XDR see anything recent"), default to a 10-minute window in sweep mode.
