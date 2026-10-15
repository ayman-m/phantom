---
name: bruteforce_vpn_to_lateral
displayName: VPN brute force chain
category: scenarios
description: 'Four-stage external-to-internal attack chain. Password spray against the org''s VPN portal → focused brute force on the one account that responded → successful auth from an anomalous geo → NDR detects unusual east-west SMB/RPC after the foothold. Vendor-agnostic — the agent resolves vendor/product from the operator''s installed data sources at runtime and uses whichever firewall, VPN, and NDR products are configured. Triggers 5 XSIAM analytics rules: Account Probing, Brute Force on Local Account, Password Spray, Impossible Travel, Anomalous Lateral Movement.'
icon: vpn_lock
source: platform
loadingMode: on-demand
locked: false
attack:
  - 'TA0001: Initial Access (T1078 Valid Accounts, T1133 External Remote Services)'
  - 'TA0006: Credential Access (T1110.001 Password Guessing, T1110.003 Password Spraying)'
  - 'TA0008: Lateral Movement (T1021.002 SMB/Windows Admin Shares, T1021.001 Remote Desktop Protocol)'
---

# Skill: Brute force → VPN compromise → Lateral movement

## Category

scenarios

## Attack Type

External credential attack progressing through perimeter authentication into east-west movement. Models the most common "ransomware operator's first hour": spray a set of likely usernames against the public VPN portal, pivot to focused brute force when one account responds, ride the successful authentication into an anomalous-geo session, and use the foothold for SMB/RPC reconnaissance against internal hosts.

## MITRE ATT&CK Tactics

- TA0001: Initial Access (T1078 Valid Accounts, T1133 External Remote Services)
- TA0006: Credential Access (T1110.001 Password Guessing, T1110.003 Password Spraying)
- TA0008: Lateral Movement (T1021.002 SMB/Windows Admin Shares, T1021.001 Remote Desktop Protocol)

## XSIAM analytics rules triggered

| # | Rule | Stage that fires it |
|---|---|---|
| 1 | Account Probing — single source attempting many distinct accounts | Stage 1 |
| 2 | Brute Force on a Local Account — many failed logons against one user | Stage 2 |
| 3 | Password Spray — many sources, many users, low per-user rate | Stage 1 |
| 4 | Impossible Travel / Anomalous Geo Sign-in | Stage 3 |
| 12 | Anomalous Lateral Movement (SMB/RPC) | Stage 4 |

## Data classes used (resolved from the operator's installed data sources at runtime)

| Stage | Data class | Why this class | If missing from stack |
|---|---|---|---|
| 1 | `firewall` | External denied-flow signal at the perimeter | Skip Stage 1's perimeter view; rely on VPN-side fail events instead |
| 1, 2, 3 | `vpn` | Authentication outcomes (success/failure) per user | Required — skill cannot meaningfully run without VPN auth telemetry |
| 4 | `ndr` | East-west traffic anomalies after foothold | Substitute with `firewall` internal-zone deny/allow events, OR skip Stage 4 |

## Pre-flight — read the operator's stack

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

Before generating any data, call `data_sources_installed_as_vendors` once. Group `vendors[]` by `data_source_class` into a category → entry lookup. The recipes below reference the entry as `<stack[<class>].vendor>` / `<stack[<class>].product>` — substitute the real values from the operator's installed data sources at execution time; call `data_sources_get_schema(<entry>.data_source_id)` per stage when a recipe needs `schema_override`. **Never hardcode vendor names in your tool calls** — the same skill must work whether the operator is running PANOS firewall + F5 APM VPN + Vectra NDR, or any other combination.

### Class check (MANDATORY — before creating any worker)

1. Call `data_sources_installed_as_vendors` once. Group `vendors[]` by `data_source_class`.
2. For every row of the "Data classes used" table, write down the installed entry you will use for it, or `MISSING`. A class is only covered by an installed entry. A generic or catch-all schema is never a substitute, and never guess a vendor/product for a class.
3. `vpn` (Stages 1-3) is required. If it is `MISSING`, say this to the operator, with the class filled in: "No installed data source covers the `<class>` class, so I cannot run the VPN brute force chain scenario. Install a `<class>` data source from the Marketplace and ask again." Then stop: create no worker.
   If `firewall` (Stage 1) is `MISSING`, skip Stage 1's perimeter view and rely on the VPN-side failure events. If `ndr` (Stage 4) is `MISSING`, use the `firewall` entry's internal-zone deny/allow events; with no `firewall` entry either, skip Stage 4. Say each substitution or skip with: "No installed data source covers the `<class>` class, so I am skipping Stage <N> (<stage name>). I will not generate it with a generic schema. Install a `<class>` data source from the Marketplace to include it."
4. In your final report, list every stage you skipped or substituted and which of the alerts above will therefore not fire.

The `destination` for every stage is the store reference `logdest:<id>` resolved in Pre-flight.

---

## Pre-flight: read the organization

Every identity in this chain comes from the active organization, never from your own invention. Call
`organization_get(section="personas")` once and, for the victim and the targets, `organization_get(section="people", filter="site=Remote")`, `organization_get(section="hosts", filter="role=server")` for the file and backup servers and `organization_get(section="hosts", filter="role=dc")` for the domain controller. The chain's actors:

- **VPN gateway (Stages 1-3):** the organization's VPN host, PHDMZ-VPN01 (`organization_get section=hosts filter=role=dmz`). Its internal address (`172.16.10.12` on Phantom Lab) is the `dst` in the firewall and NDR recipes, its hostname is the gateway name in VPN events, and its public address is `egress.dmz_public.PHDMZ-VPN01` (`organization_get section=egress`; `151.254.90.12` on Phantom Lab) for any field that carries the translated or public side.
- **Compromised user:** one ordinary person from `section=people filter=site=Remote` who is in SG-VPN-Users. Skip anyone carrying a persona flag (contractor, leaver, VIP, outlier). Take the user's login, workstation and the workstation address. Phantom Lab example: `jaljuhani` (Joud Aljuhani, Sales Engineer), workstation PHWS-033 at `10.20.200.10`, home address `77.31.81.27`.
- **VPN session address (`assignedIp`):** the compromised user's own workstation address, which sits in the VPN pool (`section=networks`, the `vpn` network, `10.20.200.0/22` on Phantom Lab). Never hand out an address outside that pool, and never give an office user a pool address.
- **Internal pivot host (Stage 4):** that same workstation (`PHWS-033`, `10.20.200.10` on Phantom Lab). Its name goes in `shost`.
- **Lateral-target hosts (Stage 4):** three high-value hosts from the organization: a domain controller (PHDC01, `10.20.0.10`), the file server (PHSRV-FS01, `10.20.1.20`) and the backup server (PHSRV-BKP01, `10.20.1.27`). These are the Phantom Lab values; on another organization take the hosts whose `purpose` is domain controller, file server and backup server.
- **Spray usernames:** the generic guesses in the Stage 1 recipe plus the logins of the organization (`organization_get section=accounts limit=100`). The compromised user's login must be in the list.
- **Domain:** the company's own name is the organization's `domain.dns` (`phantom.lab` on Phantom Lab) and its staff address is `email` from the people row. If the organization has no VPN host, no remote worker or no backup server, tell the operator what is missing and offer `organization_update` instead of inventing one.

Attacker data is not part of the organization and stays as written:

- **Attacker source IPs (Stage 1 spray):** 12 IPs across the public ranges `45.142.122.0/24`, `185.220.101.0/24`, `194.165.16.0/24` (distributed source pattern that defeats single-IP rate limits)
- **Attacker source IP (Stage 2 focused):** `185.220.101.42` (Tor exit, threat-intel known-bad)
- **Successful-auth source IP (Stage 3):** `185.220.101.42` (same as Stage 2)
- **Successful-auth source country (Stage 3):** `RU`, anomalous against the user's normal sign-in country (the organization's country, `SA` on Phantom Lab, from the user's `home_ip`)
- **Session id:** `VPN-SESS-7f3a9c2b`
- **Wall-clock time:** Stage 1 spans ~35 min (slow spray), Stage 2 ~3 min (fast burst), Stage 3 single event, Stage 4 ~12 min of east-west traffic

---

### Stage 1 — Password spray (many sources, many users) — ~500 events over 35 minutes

The attacker distributes ~500 low-rate authentication attempts across 12 source IPs against ~80 likely usernames. Per-IP rate is below typical "X failed logons in Y seconds" thresholds; per-user rate is below local-account brute-force thresholds. The pattern is only visible when the SIEM aggregates across (many sources, many users) in a window.

**Sub-stage 1A — perimeter denials (firewall sees the spray as repeated fresh TCP flows to the VPN port)**

**Data class:** `firewall`
**Format:** `CEF` (delivery doctrine — always CEF to the broker)
**MITRE technique:** T1110.003 Password Spraying

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[firewall].vendor>
  product: <stack[firewall].product>
  count:    1
  interval: 7
  max_events: 300
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src: ["45.142.122.18", "45.142.122.91", "45.142.122.114",
             "185.220.101.42", "185.220.101.74", "185.220.101.119",
             "194.165.16.12", "194.165.16.45", "194.165.16.88",
             "194.165.16.201", "194.165.16.244", "45.142.122.252"]
    dst:        ["<VPN gateway internal address: 172.16.10.12 for PHDMZ-VPN01>"]
    dpt:      ["443"]
    spt:      ["49152", "51234", "57890", "60123", "62456"]
    proto:      ["6"]
    act:        ["allow"]
    app:           ["ssl"]
    out:    ["480", "560", "320", "640", "412"]
    in: ["1240", "980", "1520"]
    country:       ["RU", "BG", "RO", "MD"]
```

**Field semantics:**
- `src_ip` — distributed attacker pool; intentionally 12 IPs across 3 known-Tor / known-bad-hosting netblocks
- `dst_ip` — the organization's VPN gateway, PHDMZ-VPN01 (`172.16.10.12` on Phantom Lab). If the firewall schema has a translated or public destination field, fill it with the gateway's public address from `egress.dmz_public.PHDMZ-VPN01`
- `dst_port` — `443` because most VPN portals use HTTPS for client login
- `action: allow` — the firewall ALLOWS these (the rule lets `0.0.0.0/0 → PHDMZ-VPN01:443` through; the actual auth result happens at the VPN itself in sub-stage 1B)
- `app` — application-id as the firewall classifies it; `ssl` because the auth payload is inside the TLS tunnel, opaque to the firewall
- `country` — geo enrichment if the firewall does it; spread across 4 high-risk countries to reinforce the distributed-source signal

**Why this fires the analytics:** the firewall log alone doesn't fire a rule (it's just normal-looking allowed traffic), but it provides the **external reconnaissance evidence** an analyst pivots to once Stage 2 fires. This is the breadcrumb that proves "this wasn't a single-IP attack."

**Sub-stage 1B — VPN auth failures (the spray itself, as the VPN sees it)**

**Data class:** `vpn`
**Format:** `CEF` (delivery doctrine — always CEF to the broker)
**MITRE technique:** T1110.003 Password Spraying

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[vpn].vendor>
  product: <stack[vpn].product>
  count:    180
  interval: 12
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src: ["45.142.122.18", "45.142.122.91", "45.142.122.114",
             "185.220.101.42", "185.220.101.74", "185.220.101.119",
             "194.165.16.12", "194.165.16.45", "194.165.16.88",
             "194.165.16.201", "194.165.16.244", "45.142.122.252"]
    user:                  ["administrator", "admin", "root", "guest", "service",
                            "test", "demo", "support", "helpdesk", "backup", "operator",
                            "scanner", "monitor", "audit", "compliance", "security",
                            "manager", "director", "ceo", "cfo", "cto", "ciso",
                            # plus every login from organization_get(section="accounts", limit=100):
                            # staff logins, adm.* administrators, svc-* service accounts, adm.breakglass.
                            # Phantom Lab gives 64, so the list reaches ~86 distinct names. Keep it at 80 or more,
                            # and make sure the compromised user's login is one of them.
                            "<login of the compromised user>", "<every other login from the accounts section>"]
    act:                ["login_failure"]
    authenticationResult: ["failed"]
    authenticationMethod: ["password"]
    errorCode:            ["AUTH_FAILED", "INVALID_CREDENTIALS"]
    externalId:            []
    cefSeverity:              ["medium"]
    country:               ["RU", "BG", "RO", "MD"]
```

**Field semantics:**
- `user` — 80 or more distinct candidate usernames: generic admin and role defaults plus the real logins of the organization (staff, administrators, service accounts), so the spray hits accounts that exist in the directory
- `action`, `authentication_result` — the VPN's two parallel ways of expressing the same fact; populate both so the SIEM's rule matches whichever field its parser uses
- `authentication_method: password` — distinguishes from MFA / cert / SAML; password-only attempts are the ones brute-force rules key on
- `error_code` — vendor-neutral failure reasons; the SIEM's parser typically normalises these to a `failure_reason` ECS field
- `session_id` — empty `[]` because no session is established on a failed auth
- `country` — geo enrichment if the VPN does it (some products do, some don't — including it doesn't hurt)
- `vpn_gateway` — the portal hostname (PHDMZ-VPN01); lets analysts filter by which appliance saw the attempts

**Why this fires the analytics:**
- **Rule #3 (Password Spray):** the SIEM detects ≥10 distinct users attempted from a pool of distinct sources within the window, with low per-user rate. The 80 users × 12 sources × 35-min window pattern fires this cleanly. Threshold typically: ≥10 users, ≤5 attempts per user, ≥5 distinct sources.
- **Rule #1 (Account Probing):** the spray's distribution by user-count from any single source IP also crosses the account-probing threshold (typically ≥10 distinct users from one source in 5 min). A small subset of the source IPs (those given more usernames in the rotation above) hit this threshold individually.

---

### Stage 2 — Focused brute force on the one responsive account — ~50 events over 3 minutes

After the spray, the attacker has identified that the compromised user's login (`jaljuhani` on Phantom Lab) is a real account (it returned a different error code or response time). They now focus all their energy from one source against that one user, hammering passwords from a leaked-credential list.

**Data class:** `vpn`
**Format:** `CEF` (delivery doctrine — always CEF to the broker)
**MITRE technique:** T1110.001 Password Guessing

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[vpn].vendor>
  product: <stack[vpn].product>
  count:    1
  interval: 4
  max_events: 50
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:                ["185.220.101.42"]
    user:                  ["<login of the compromised user>"]
    act:                ["login_failure"]
    authenticationResult: ["failed"]
    authenticationMethod: ["password"]
    errorCode:            ["INVALID_CREDENTIALS"]
    cefSeverity:              ["high"]
    country:               ["RU"]
```

**Field semantics:**
- `src_ip` — single source now (one of the spray IPs from Stage 1)
- `user` — single account being hammered
- `severity: high` — many vendors auto-escalate severity once they see >N failures for one user; populate it to reflect the realistic SIEM ingestion shape
- `interval: 4` — 4 seconds between attempts means ~50 attempts in 3 minutes; well above any "brute force on local account" threshold (typically 10 attempts in 60s)

**Why this fires the analytics:**
- **Rule #2 (Brute Force on Local Account):** classic 1-source-1-user-many-fails pattern. SIEM thresholds are usually ≥10 failed attempts against the same user from the same source in ≤60 seconds.
- **Rule #1 (Account Probing) — reinforces:** the same source IP that participated in Stage 1's spray now shows up with concentrated activity, strengthening the account-probing finding.

---

### Stage 3 — Successful auth from anomalous geo — 1 event

After ~50 fails, the attacker hits the right password. One successful auth from the same source IP, same user, but the user's normal sign-in baseline is the organization's own country (`SA` on Phantom Lab). This single event is the "the brute force succeeded" signal.

**Data class:** `vpn`
**Format:** `CEF` (delivery doctrine — always CEF to the broker)
**MITRE technique:** T1078 Valid Accounts

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[vpn].vendor>
  product: <stack[vpn].product>
  count:    1
  interval: 1
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:                ["185.220.101.42"]
    user:                  ["<login of the compromised user>"]
    act:                ["login_success"]
    authenticationResult: ["success"]
    authenticationMethod: ["password"]
    externalId:            ["VPN-SESS-7f3a9c2b"]
    assignedIp:           ["<the compromised user's workstation address in the VPN pool: 10.20.200.10 for jaljuhani>"]
    cefSeverity:              ["informational"]
    country:               ["RU"]
```

**Field semantics:**
- `action: login_success` + `authentication_result: success` — the auth went through
- `session_id` — populated now (the VPN issues a session token); the same value should appear in any post-auth event for this session
- `assigned_ip` — the internal IP the VPN assigns to this session (from the organization's VPN pool, `10.20.200.0/22` on Phantom Lab; it is the address of the compromised user's own workstation). This is critical for Stage 4: the SIEM correlates "what does this user's VPN session do once it's inside?"
- `country: RU` vs the user's normal `SA` baseline — the impossible-travel detection fires on the geographic delta within the user's session history

**Why this fires the analytics:**
- **Rule #4 (Impossible Travel / Anomalous Geo Sign-in):** the user's last successful sign-in was from `SA` within hours; this one is `RU`. Geographic distance / time-since-last-login produces an impossible-travel signal regardless of the SIEM's specific algorithm.

**Note on baseline establishment:** for the impossible-travel rule to fire, the SIEM needs at least one prior `country: SA` successful sign-in for the compromised user in its baseline. If the operator is testing on a fresh tenant, you should pre-seed the baseline by running a small recipe of "normal sign-ins from the user's home country" first, using the user's own `home_ip` from the organization:

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[vpn].vendor>
  product: <stack[vpn].product>
  count:    1
  interval: 3600
  max_events: 8
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:    ["<home_ip of the compromised user: 77.31.81.27 for jaljuhani>"]
    user:      ["<login of the compromised user>"]
    act:    ["login_success"]
    country:   ["SA"]
    authenticationResult: ["success"]
    authenticationMethod: ["password", "mfa"]
    cefSeverity:  ["informational"]
```

Skip the baseline pre-seed if the SIEM tenant has been operational for >2 weeks — real activity is plenty.

---

### Stage 4 — Anomalous east-west lateral movement — ~100 events over 12 minutes

The attacker is now inside (VPN session active, internal IP the compromised user's VPN-pool address, `10.20.200.10` on Phantom Lab). Within minutes they pivot to internal hosts using SMB and RPC — the workstation makes connections it has never made before in its history. NDR detects the deviation from learned baseline.

**Data class:** `ndr`
**Format:** `CEF` (delivery doctrine — always CEF to the broker)
**MITRE techniques:** T1021.002 SMB/Windows Admin Shares, T1021.001 RDP

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[ndr].vendor>
  product: <stack[ndr].product>
  count:    100
  interval: 7
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["<compromised user's workstation address: 10.20.200.10>"]
    shost:      ["<compromised user's workstation: PHWS-033>"]
    dst:        ["10.20.0.10", "10.20.1.20", "10.20.1.27"]
    dhost:      ["PHDC01", "PHSRV-FS01", "PHSRV-BKP01"]
    dpt:      ["445", "139", "3389", "5985"]
    proto:      ["6"]
    act:        ["alert", "monitor"]
    anomalyType:  ["lateral_movement", "unusual_internal_connection",
                    "smb_admin_share_access", "rdp_to_uncommon_destination"]
    anomalyScore: ["72", "85", "91", "68", "77"]
    alertName:    ["Unusual SMB to admin$ share",
                    "First-time RDP from workstation to server",
                    "Lateral RPC pattern matching admin tooling"]
    alertType:    ["ndr_lateral_movement", "ndr_anomaly"]
    cefSeverity:      ["high", "medium"]
    attackCategory: ["lateral_movement"]
    attackType:     ["smb_admin_access", "rdp_lateral"]
    out:     ["240", "1024", "4096", "8192", "16384"]
    in: ["180", "512", "2048", "8192"]
    suser:   ["<login of the compromised user>"]
    externalId:     ["VPN-SESS-7f3a9c2b"]
```

**Field semantics:**
- `src_ip` / `src_host` — match the VPN's `assigned_ip` from Stage 3 so the chain links via the session
- `dst_ip` / `dst_host` — three internal high-value targets: domain controller, file server, backup server
- `dst_port` — `445` (SMB), `139` (NetBIOS, often correlated with SMB), `3389` (RDP), `5985` (WinRM) — the "lateral movement" port quartet
- `anomaly_type` — multiple values populate so the SIEM matches whichever taxonomy it uses; some products use `lateral_movement`, others use specific names like `smb_admin_share_access`
- `anomaly_score` — typical NDR confidence range; values 70-91 trigger high-severity rules
- `alert_name` — populate with realistic NDR alert text the SIEM will display
- `account_name` — the username from the VPN session, propagated from Stage 3 — this is what makes the chain attributable to the compromised user
- `session_id` — same value as Stage 3, so the SIEM can correlate "VPN session VPN-SESS-7f3a9c2b → 100 SMB/RPC anomalies"

**Why this fires the analytics:**
- **Rule #12 (Anomalous Lateral Movement):** the compromised user's workstation (PHWS-033 on Phantom Lab) has no historical baseline of SMB to PHDC01, RDP to PHSRV-FS01, etc. — the NDR's baseline-deviation detector fires. Some products name this differently ("Unusual Internal Connection", "First-Time Admin Share Access") but the analytic family is the same.

**If the operator's stack has no NDR:** substitute with `firewall` internal-zone deny/allow events showing the workstation's east-west traffic. The substitution recipe:

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[firewall].vendor>
  product: <stack[firewall].product>
  count:    1
  interval: 7
  max_events: 100
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["<compromised user's workstation address: 10.20.200.10>"]
    dst:        ["10.20.0.10", "10.20.1.20", "10.20.1.27"]
    dpt:      ["445", "139", "3389", "5985"]
    proto:      ["6"]
    act:        ["allow"]
    app:           ["smb", "rpc", "ms-rdp", "ms-winrm"]
    out:     ["240", "1024", "4096", "8192", "16384"]
```

The substitution is weaker — firewall east-west allow events don't fire the lateral-movement rule on their own; they're at best evidence the analyst correlates after another rule fires. **Note this in the post-skill summary** so the operator understands the coverage gap.

---

## Verification

After running all four stages, the operator should see (within ~5 min of Stage 4 completing):

| Indicator | Where to check |
|---|---|
| ≥1 alert matching "Password Spray" / "Distributed Brute Force" / "Account Enumeration" | XSIAM Issues, last 60 min |
| ≥1 alert matching "Brute Force on Local Account" / "Account Lockout Risk" | XSIAM Issues, last 60 min |
| ≥1 alert matching "Impossible Travel" / "Anomalous Geo Login" | XSIAM Issues, last 60 min |
| ≥1 alert matching "Lateral Movement" / "Unusual Internal Connection" | XSIAM Issues, last 60 min |
| Pivotable correlation: `user=<compromised user's login>` + `session_id=VPN-SESS-7f3a9c2b` | XQL query: `config timeframe = 24h \| dataset = <dataset_name of the vpn entry> | filter <its user field> = "<compromised user's login>" \| limit 20` then pivot to NDR via session_id |

If any of the four expected alerts is missing, the issue is one of:
- The data class wasn't in the operator's tech stack → check pre-flight output
- The SIEM's parser maps the field names differently → query the raw events with `xsiam.get_issues` and inspect what fields actually got populated
- The threshold for the rule is higher than this skill's volume → bump the relevant stage's `count`

## Tear-down

This skill creates 4 data workers. To stop them mid-run (or to clean up after completion if any are still streaming):

```yaml
xlog.list_workers:
  # returns active worker IDs

xlog.kill_worker:
  worker_id: <each ID returned above>
```

The skill is non-destructive on the SIEM side — the events are already ingested. If the operator wants to suppress the test alerts so they don't pollute real-incident triage, mark them resolved with `xsiam.alerts_update` (`alert_id_list` from the matching `xsiam.get_issues` results, `update_data: {status: "resolved_other"}` or similar) after verification.

## Adapting per deployment

The attacker addresses (`185.220.101.42` and the other spray sources) are illustrative. Every company identity (the VPN gateway, the compromised user, the pivot workstation, the lateral targets and the spray logins) comes from the active organization (`organization_get`). To run the chain against a different person or gateway, the operator can ask in chat ("run the bruteforce_vpn_to_lateral skill against the CFO's account", "use a Jeddah user"); read that person or host from the organization and keep the chain shape and rule-trigger logic. If the organization lacks something the chain needs, tell the operator and offer `organization_update`.
