# Syslog/CEF vs other collection paths — does the way a log arrives change which analytics detectors fire?

**Date:** 2026-09-30 · **Tenant:** STC · **Generator:** stc-engine (phantom v0.17.165, release track)
**Companion scripts:** `scripts/experiments/` (`stc_api.py`, `exp1_dns_tunnel.py`, `exp2_dcsync.py`, `exp2b_dcsync_story.py`, `exp3_kerberoast.py`, `exp4_ldap_enum.py`, `exp5_account_mgmt.py`, `exp6_delegation_tgt.py`)

## Findings so far (14:15 local checkpoint)

1. **Six technique families fired over pure syslog/CEF — every one landed and XQL-verified**
   (~160 events): DNS tunneling (FortiGate `dns-response`), DCSync (4662 + full
   4624→4672→4688 story on one Logon ID), Kerberoasting (4769 RC4 sweep), AD admin-group LDAP
   enumeration (1644), account-management attack (4728/4720/4726/4740), machine-account +
   delegation abuse + TGT burst (4741/4742/4729/4768). Each reached the exact XDM fields its
   detector reads.
2. **Alert board: zero** `XDR_ANALYTICS`/`XDR_ANALYTICS_BIOC` in 48 h despite the above. Exp 1
   passed the port-scan detector's historical 3.5–12 min firing window within its first half-hour.
   The detectors under test behave like the baselined/slow class (cf. Spam Bot Traffic), not the
   instant-shape class (Port Scan).
3. **No evidence of collector-side gating yet.** Six sources, six modeling rules; the modeled
   output carried every field the relevant rule reads (we have no vendor-native feed on this tenant
   to compare against, so "identical to native" is not claimed). Everything that has historically
   refused to fire on this tenant did so for rarity/volume/baseline reasons that apply to real
   traffic equally.
4. **Structural limits found (content, not transport):** FortiGate qtype ladder does not know
   `NULL`; Windows 4662 has no structured Properties/AccessMask mapping — replication GUIDs ride
   in `xdm.event.description` only (a detector regexing the description still works; one keyed on
   a structured field never will, from *any* transport into this dataset).
5. **Deciding test queued:** if the board stays quiet, the A/B is per-source: Windows events via
   the Broker VM **WEC applet** (Windows Event Forwarding) instead of CEF, and JSON sources via an
   **HTTP collector**. FortiGate is already collected by syslog in production, so it needs no A/B.
   If the other path fires where our CEF did not, the collection path is a signal; if both stay
   quiet, the gate is baseline/licensing.

## The question

Cortex ingests logs through several collection paths: the Broker VM (syslog/CEF), an HTTP collector,
S3, GCP Pub/Sub, and the Broker's WEC applet for Windows Event Forwarding. Phantom only speaks
**CEF/syslog to the Broker**. The governing question for phantom's value as an analytics-triggering
tool:

> Does the Cortex analytics engine care **how** a log arrived, or only what the parsing +
> modeling rules produce from it?

## Working hypothesis (being tested)

Analytics detectors read **XDM columns**, which are produced by parsing + modeling rules keyed
on the syslog/CEF `vendor`/`product` header pair, so the transport is invisible downstream.
If true, syslog is sufficient for every detector whose signal survives the modeling rule.

**Possible exceptions (all UNVERIFIED hypotheses, none measured here):**

1. **Enrichment-side context**: identity graph, asset classification (e.g. "this host is a
   domain controller"), story-layer causality. These would be built by the tenant from inventory
   and endpoint telemetry, not from log payloads, so no log format could inject them.
2. **WEC/endpoint telemetry**: logs forwarded by the WEC applet might land in a different dataset
   family (endpoint events) and unlock endpoint BIOCs that no syslog source can reach.
3. **HTTP collector**: possibly convenience, not capability: it accepts JSON-native payloads so no
   reverse-engineering of a CEF mapping is needed, and the modeled result should be the same.

## Experiments fired

### Exp 1 — DNS Tunneling via FortiGate CEF (`exp1_dns_tunnel.py`)

- **Recipe:** a DNS-tunneling pattern (40–90 high-entropy base32 qnames under one stable tunnel
  domain, TXT-heavy qtypes, one internal host → one external resolver, UDP/53), expressed in
  phantom's *verified* FortiGate `dns-response` field shape.
- **Worker:** `worker_20260930075908` — 80 events over 120 s, `Fortinet`/`Fortigate` (lowercase g),
  `WS-STCE-12` (10.20.63.12) → 203.0.113.53, domain `t.exfil-tunnel.net`.
- **Landing: VERIFIED.** `xdm.network.dns.dns_question.name` + `.type` populate (TXT/A/CNAME),
  `xdm.event.type = dns-response`, correct src/dst. The DNS XDM subtree is reachable over CEF.
- **Alert:** pending at time of writing (~45 min). Comparison points: Suspicious Port Scan fires
  in 3.5–12 min; Spam Bot Traffic needed hours. DNS Tunneling / Random-Looking Domain Names are
  likely baselined detectors, so a long watch window applies.
- **Note:** phantom's qtype enum ladder does not recognize `NULL`; we skipped it. If the detector
  keys on NULL queries specifically, that is a *content* gap in the pack's modeling rule, not a
  transport gap.

### Exp 2 — DCSync via Windows CEF (`exp2_dcsync.py`, `exp2b_dcsync_story.py`)

- **v1 (4662-only):** `worker_20260930082914` — 4 × Event 4662, subject `ahmed.alharbi`
  (WS-1001 / 10.20.14.11), Access Mask `0x100`, target `CN=krbtgt,CN=Users,DC=stc,DC=local`,
  four replication GUIDs (1131f6aa/ad/ae…, 89e95b76…) in the message prose.
- **v2 (full story):** `worker_20260930090730/32/35/40` — 4624 (elevated network
  logon) → 4672 (special privileges) → 4688 (`mimikatz.exe "lsadump::dcsync /user:krbtgt"` process
  creation) → 4 × 4662, all sharing Logon ID `0x1A2B3C`.
- **Landing: VERIFIED.** `xdm.event.original_event_type` resolves to Logon / Special Logon /
  Process Creation / Directory Service Access respectively; outcome SUCCESS; user-host binding
  intact; **the replication GUIDs survive in `xdm.event.description`** — confirmed to be the only
  XDM field carrying the full message (`coalesce(message, …)`), because
  `MicrosoftWindowsEvents_2_11.xif` has no dedicated Properties/AccessMask mapping for 4662.
- **Alert:** pending at time of writing.
- **Risk noted:** "Possible DCSync from a non domain controller" may require a field the CEF path
  cannot express (e.g. a structured replication-GUID column) or may be license/module-gated — if
  v2 doesn't fire within a few hours, that is evidence *for* a collector/dataset dependency, and
  a WEC-applet A/B becomes the deciding test.

### Exp 3 — Kerberoasting sweep via Windows CEF (`exp3_kerberoast.py`)

- **Worker:** `worker_20260930091618` — 15 × Event 4769 with `TicketEncryptionType 0x17` (RC4)
  against an AES256 baseline, 5 service SPNs (MSSQLSvc/HTTP/CIFS/ldap/TERMSRV), one user.
- **Landing: VERIFIED** — `xdm.event.original_event_type = "Kerberos Service Ticket Operations"`,
  per-SPN service names intact in `xdm.event.description`.

### Exp 4 — AD admin-group enumeration via LDAP (`exp4_ldap_enum.py`)

- **Worker:** `worker_20260930092421` — 5 × Event 1644 from one client (WS-1001), filter swept
  across Domain Admins / Enterprise Admins / Schema Admins / Administrators / `adminCount=1`.
  Provider `Microsoft-Windows-ActiveDirectory_DomainService`, channel omitted per the verified
  recipe (model gate clears on the provider disjunct).
- **Landing: VERIFIED** — all 5 rows landed. Note: canonical_task resolves from the message's
  first token (`Internal event`), not a named taxonomy — cosmetic only.
- **Target detector:** `administrator-groups-enumerated-via-ldap` — documented UNGATED, Test
  Period N/A (single event), T1087. The strongest single-event candidate in this batch.

### Exp 5 — Account-management attack batch (`exp5_account_mgmt.py`)

- **Workers:** `…092750/56/…092801/06` — 4728 (member added to Domain Admins) ×2, 4720 (account
  created) ×2, 4726 (account deleted) ×8, 4740 (locked out) ×6. Actor `ahmed.alharbi`, Logon
  `0x1A2B3C`, logged on DC01.
- **Landing: VERIFIED** — `Security Group Management` ×2, `User Account Management` ×15.

### Exp 6 — Machine accounts, delegation abuse, TGT burst (`exp6_delegation_tgt.py`)

- **Workers:** `…093347/53/58/…093404` — 4741 (rogue machine account `EVIL-WS01$`) ×1, 4742
  (`'Trusted For Delegation' Enabled`) ×2, 4729 (member removed from Domain Admins) ×1, 4768
  TGT burst ×20 in 60 s from one user.
- **Landing: VERIFIED** — `Computer Account Management` ×3, `Security Group Management` ×1,
  `Kerberos Authentication Service` ×20.

## Next-step plan for the collection-path A/B

- [ ] Keep waiting on the in-flight syslog experiments (watcher armed; Exp 1 oldest at ~2.5 h)
- [ ] If DCSync stays silent: enable the Broker VM **WEC applet** and replay the same Windows events
      as native Windows event XML: the decisive syslog-vs-WEC A/B
- [ ] Optionally: HTTP collectors for Okta and Proofpoint (Log Format JSON, uncompressed, vendor and
      product set on the collector) to open identity/email detector families; these test new detector
      families rather than re-testing the firewall/Windows ones
- [ ] AWS/GCP stay out of scope unless we want S3/Pub/Sub plumbing (their detectors are
      cloud-audit-family, lower priority for this tenant)

## Recurring pressure jobs (16:00 local)

Five `exp-*` jobs now live on stc-engine, all `tool_call` → `xlog.create_data_worker`, tagged
`experiment`, timestamps self-dating via `{{now:strftime}}` (verified: a manual `jobs_run_now` of
`exp-dcsync` landed at the exact fire-time epoch, not a fossilized one). Minutes chosen to dodge
the existing baseline jobs:

| Job | Cron (Asia/Riyadh) | Payload |
|---|---|---|
| `exp-dns-tunnel` | `9 */2 * * *` | 80 FortiGate `dns-response` events, 3 host + 3 domain pools |
| `exp-dcsync` | `23 */3 * * *` | 4 × 4662 w/ replication GUIDs, 2 identity pool |
| `exp-kerberoast` | `37 */3 * * *` | 15 × 4769 RC4 across 5 SPNs |
| `exp-ldap-enum` | `19 */4 * * *` | 5 × 1644 admin-group filter sweep |
| `exp-acct-mgmt` | `47 */6 * * *` | 8 × 4726 mass account deletion |

Creator script: `scripts/experiments/create_exp_jobs.py`. Re-check the alert board after a few
hours of this cadence; if still silent, the baseline-window theory is effectively dead and the
WEC A/B moves to the front.

## Re-fire round (14:45–14:50 local) — fresh entities to rule out per-entity dedup

- **Exp 1 re-run:** `worker_20260930104455` — same recipe, fresh source `WS-STCE-14`
  (10.20.63.14), fresh domain `t2.exfil-tunnel.net`. Landed: 80/80 rows on the new source IP.
- **Exp 2 re-run:** `worker_20260930104850/52/55` + `…104900` — full story with a fresh identity:
  `abdullah.alzahrani` / `WS-1002` / 10.20.14.12 / SID `…-1101` / Logon `0x2B3C4D`. Landed:
  Logon ×1, Special Logon ×1, Process Creation ×1, Directory Service Access ×4.
- Scripts are now parameterized (`EXP1_SRC_HOST`/`EXP1_SRC_IP`/`EXP1_DOMAIN`,
  `EXP2_USER`/`EXP2_SID`/`EXP2_HOST`/`EXP2_IP`/`EXP2_LOGON`) so any future re-fire with a fresh
  entity is an env-var change, not an edit.
- **Alert board after both re-runs: still zero** (48 h window).

## Alert board (as of 14:15 local, 2026-09-30)

Zero `XDR_ANALYTICS`/`XDR_ANALYTICS_BIOC` alerts in the last **48 h** despite all of the above
(and despite the baseline jobs running their benign day-in-the-life traffic throughout). Exp 1
is ~2 h 15 min old — well past the port-scan detector's historical 3.5–12 min firing window.
Hourly alert-watcher automation remains armed.

## Interim conclusions

1. **Landing over CEF/syslog works for every class we tried.** Every payload class sent so far
   (FortiGate traffic + all six UTM subsystems, Windows Security events, Entra sign-ins, PAN NGFW,
   AKS) reaches the XDM columns its modeling rule defines. (Not compared against a vendor-native
   feed; that comparison has not been made.)
2. **Firing is detector-gated, not transport-gated — so far.** The detectors that refused to fire
   on this tenant (Spam Bot on demand, SMB BIOC re-fire) did so because of rarity/volume/baseline
   gates, which apply identically to real traffic.
3. **Unresolved:** whether any analytics detector is keyed on collector-side metadata (collector
   type, ingestion method) rather than dataset content. No evidence for it yet; the DNS-Tunneling
   and DCSync watch windows are the live test. If both stay silent despite verified XDM, the
   deciding A/B uses the other collection path for each source (Windows → WEC applet; JSON sources →
   HTTP collector); see the plan above.

## Next steps

- [ ] Watch window for Exp 1–6 alerts (hourly alert-watcher automation armed)
- [x] Work through the Windows threat list via CEF — done for Kerberoasting, delegation changes,
      priv-group add/remove, account creation, mass deletion, lockouts, TGT burst (Exp 3–6)
- [ ] If silent: enable the Broker VM **WEC applet** and replay the DCSync events as native
      Windows XML (decisive Windows A/B); optionally HTTP collectors for Okta/Proofpoint
- [ ] Port every confirmed firing recipe into phantom trigger skills (and fix the known
      brute-force recipe gap: detectors need failure-*then-success*, current Entra recipe sends
      failures only)

## Update 2026-09-30 evening: Okta HTTP collector path built and verified landing

- **Built:** `okta-sso` user connector (`bundles/spark/user-connectors/okta-sso/`, issue #53) sends Okta
  System Log JSON to the STC HTTP Log Collector. Deployed on stc-engine as instance `Okta_SSO`.
  Failed-then-success, password-spray and MFA-fatigue scenarios included.
- **Verified:** 10 events accepted (HTTP 200) and found in `okta_sso_raw` by uuid (`_vendor=Okta`, `_product=Sso`).
- **Blocked, so the Okta A/B is NOT in flight:** `okta_sso_raw` is raw-only. The Okta content pack is not
  installed on STC (60 packs, none Okta), so there is no parsing rule (`_time` is ingestion time; back-dating
  via `published` does nothing) and no modeling rule (`datamodel dataset = okta_sso_raw` returns 0 rows). The
  marketplace API install of the Okta pack fails with 101704; it has to be installed from the UI.
- **After the pack is installed, check:** re-run `send_test_event`, then confirm `_time` equals `published`
  for that uuid, and that `datamodel dataset = okta_sso_raw | fields xdm.source.user.upn, xdm.event.outcome`
  returns rows. UNVERIFIED until then: whether the pack's `vendor="okta", product="sso"` ingest rule matches the
  collector's `Okta`/`Sso` stamp.
- **Even then, not analytics-ready:** every Okta detector in the catalog is behind the Identity Analytics
  module (`docs/research/analytics-detector-craftability-2026-09-30.md` §8), so entitlement and baseline still apply.
- **Platform gap found:** the agent cannot call tools of user-uploaded connectors (loader reads the bundle
  manifest only); the connector was proven through `proxy_call_tool` inside `phantom_agent` instead.

## Update 2026-10-01: `okta-sso` generalized into `http-sender`; the loader gap is fixed

- **Renamed and generalized (#58):** the connector above is now `http-sender`
  (`bundles/spark/user-connectors/http-sender/`). It sends JSON for any data source to an XSIAM HTTP
  collector; Okta is its built-in `okta` event profile (same scenarios, same event shapes), so everything
  recorded above applies unchanged to `http-sender` with `profile=okta` against the `okta_sso` destination.
  The `Okta_SSO` instance on stc-engine and the `okta_sso_raw` dataset keep their names; only the connector id changed.
- **Platform gap closed (#54):** tools of user-uploaded connectors are now visible to the agent
  (`usecase/connector_catalog.py`), so the connector no longer needs `proxy_call_tool` to be exercised.
- **Unchanged:** the Okta content pack is still the blocker for the A/B (see the checks above).

---

# 2026-10-03 — Native transports online: WEC + HTTP collectors, first scenario fires

## What changed (built via a parallel agent session)

- **WEC subscription live on the Broker VM.** Windows Security events now arrive natively
  (WS-Man/WinRM, full XML payload in `_raw_log`, `_vendor=Microsoft`, `_product=Windows`)
  from hosts `PHSRV-FS01`, `PHDC02`, `PHANTOM-WECTEST01` (event IDs 4624/4634/4662 seen).
- **HTTP collectors configured** for Okta, Google Workspace, Proofpoint TAP; new stc-engine
  tools `http-sender.generate_events` / `wec-sender.generate_events` with scenario catalogs,
  plus 16 new baseline jobs (49 jobs total on stc-engine, all enabled and running).

## Destination → dataset audit (reference simulator canonical mapping)

reference simulator source constants (`modules/*.py` XSIAM_VENDOR/XSIAM_PRODUCT):

| Destination | vendor/product sent | dataset | reference simulator canonical | Verdict |
|---|---|---|---|---|
| `okta_okta` (default!) | Okta/Okta | `okta_okta_raw` | — | **wrong** — no Okta parsing rules there |
| `okta_sso` | Okta/SSO | `okta_sso_raw` | Okta/Sso | **use this** |
| `proofpoint_tap` | Proofpoint/Tap | `proofpoint_tap_raw` | Proofpoint/Tap | correct |
| `google_workspace` | Google/Workspace | `google_workspace_raw` | Google/Workspace | **use this** |
| `google_workspace_drive` | Google Workspace/Drive | `google_workspace_drive_raw` | — | used by baselines; not reference simulator canonical |

First `password_spray` batch accidentally went to the default `okta_okta` destination and
landed in `okta_okta_raw` (vendor/product `okta/okta`) — outside the Okta content pack's
parsing scope. Re-fired everything against `okta_sso`.

## Scenarios fired (all HTTP 200, landing verified by row counts)

| Profile | Scenario | Count | Spread | Dataset |
|---|---|---|---|---|
| okta | password_spray | 60 | 600 s | `okta_sso_raw` |
| okta | failed_then_success | 30 | 900 s | `okta_sso_raw` |
| okta | mfa_fatigue | 25 | 600 s | `okta_sso_raw` |
| google_workspace | impossible_travel_login | 12 | 1800 s | `google_workspace_raw` |
| google_workspace | public_share | 15 | 900 s | `google_workspace_raw` |
| google_workspace | sensitive_download | 20 | 900 s | `google_workspace_raw` |
| proofpoint_tap | credential_phishing | 15 | 900 s | `proofpoint_tap_raw` |
| proofpoint_tap | malware_attachment | 12 | 900 s | `proofpoint_tap_raw` |
| proofpoint_tap | bec_impostor | 10 | 900 s | `proofpoint_tap_raw` |
| proofpoint_tap | click_chain | 12 | 900 s | `proofpoint_tap_raw` |

1 h counts after firing: okta_sso_raw = 118 (115 fired + baseline), google_workspace_raw = 47
(exact), proofpoint_tap_raw = 51 (49 fired + baseline).

## Data quality check (Okta)

Events parse fully: `actor.alternateId`, `client.geographicalContext` (city/country/lat/lon),
`outcome.result=FAILURE`, `outcome.reason=INVALID_CREDENTIALS`, `eventType=user.session.start`,
`published` epoch. This is structurally identical to real Okta SystemLog JSON — the exact
shape identity analytics detectors consume.

## Alert board

Still **zero** `XDR_ANALYTICS`/`XDR_ANALYTICS_BIOC` at T+~10 min after firing — expected,
identity analytics evaluation windows are longer than port-scan (which historically fired in
3.5–12 min). Watch window open; re-check at T+1 h and T+3 h.

## Known gaps / next

- [ ] **WEC threat scenarios missing**: `wec-sender` profile `windows` only ships
      `baseline_logons`. DCSync/Kerberoasting/account-mgmt scenarios from reference simulator's
      `modules/windows_events.py` `_THREAT_GENERATORS` need porting into wec-sender to run the
      decisive Windows A/B (native WEC vs our earlier syslog CEF, which landed but never fired).
- [ ] Consider repointing the `http-baseline-okta-*` and `http-baseline-gdrive-*` jobs to the
      canonical destinations (`okta_sso`, `google_workspace`) if not already.
- [ ] Re-check alert board at T+1 h / T+3 h; if identity detectors fire, port recipes to
      phantom trigger skills.


## XDM modeling verification (2026-10-03, ~16:10 UTC+3)

| Dataset | XDM modeled? | Notes |
|---|---|---|
| `okta_sso_raw` | **yes** | `xdm.event.outcome` SUCCESS/FAILED + `xdm.source.user.upn` populated — Okta pack now active (was missing on 2026-09-30) |
| `proofpoint_tap_raw` | **yes** | modeled (email/alert event family; outcome/upn null as expected) |
| `microsoft_windows_raw` | **yes** | WEC events: `xdm.event.type=Security`, outcome SUCCESS |
| `google_workspace_drive_raw` | **yes** | `xdm.event.type=access` — **this is the modeled GW dataset on this tenant** |
| `google_workspace_raw` | **no** (0 rows) | reference simulator's canonical target, but the installed pack here only models the drive dataset |

**Correction applied:** GW attack scenarios re-fired against destination `google_workspace_drive`
(impossible_travel_login ×12, public_share ×15, sensitive_download ×20) so they join the modeled
dataset alongside the running baselines.

**Remaining data-source fix:** the `http-baseline-gdrive-*` jobs already target the drive
destination — good. The `okta_okta` default destination is still a trap; scenario calls must
always pass `destination=okta_sso` explicitly.

## Exp 7 (2026-10-03 ~16:45 UTC): Kerberos relay pattern via syslog — two-step test, step 1

Context: of the 57 WEC-reading detectors in the catalog, only **5 are ungated** (no Identity
Analytics module requirement): LDAP admin enum, Mailbox CAS changed, **Kerberos relay**, and the
two Exchange PowerShell ones. `pan_dss_raw` has **0 rows in 30 days**, so Cloud Identity Engine
appears unpaired — meaning the ~49 Identity-Analytics-gated WEC detectors and all 32 Okta
detectors cannot fire regardless of log shape until the module is enabled. The ungated 5 are
the only near-term Windows wins; Kerberos relay is the most craftable.

- Fired `worker_20261003164518`: 12× 4624 (LogonType 3, NtLmSsp/NTLM) on `PHSRV-FS01.phantom.lab`
  where **Source Network Address = the host's own IP** (10.20.16.10) — the relay loopback
  signature — across 4 phantom.lab users. Script: `scripts/experiments/exp7_kerberos_relay.py`.
- Landed: 12/12 verified in `microsoft_windows_raw` with full message text.
- **If it alerts:** transport-independent, detector live. **If silent:** the same payload goes
  over WEC as soon as `wec-sender` gains a threat scenario — that is the decisive A/B for
  collector-type gating.

## Exp 8–10 (2026-10-04 ~02:40–03:05 UTC): crafted threats over native WEC via `send_events`

**Key unlock:** `wec-sender.send_events` accepts caller-supplied structured events rendered to
Windows XML by the connector — the P1/P2 pick list fires **today**, no built-in scenarios needed.
Catalogued ids (4624/4625/4634/4672) get real rendering free; any other id just needs
`provider` + `rendering.message`/`rendering.task`.

| Batch | Script | Contents | Events | Landing |
|---|---|---|---|---|
| Exp 8 | `exp8_wec_threats.py` | Kerberos relay 12× 4624 (Exp 7 step 2, WEC leg); DCSync 4624 story + 4× 4662 repl GUIDs (`phantom.repltest`, non-DC); 4728 machine acct `PHWS-110$` → Domain Admins | 18 | 18/18 verified, `_collector_type=WEC` |
| Exp 9 | `exp9_wec_singles.py` | 4738 pwd-never-expires, 4616 time change, 4722 Guest enable, 4720 local "Administrator", 4724 sensitive pwd reset, 4781 rename to `PHDC02$`, 4742 SPN-cleared, 4742 delegation | 8 | 8/8 verified |
| Exp 10 | `exp10_wec_kerberos_bursts.py` | 18× 4769 RC4 distinct SPNs (#22/#23), 8× 4768 PreAuthType 0 (#25), 10× 4768 burst one user (#24) | 36 | accepted 36/36 |

**Modeling verified:** 4662 lands with full `event_data` JSON (repl GUIDs, AccessMask 0x100) and
`xdm.event.description` carrying the complete message text — the exact carrier the DCSync
detector reads. All batches appear in `datamodel dataset = microsoft_windows_raw` with correct
`xdm.event.original_event_type` and hostnames.

**Alert board: zero** `XDR_ANALYTICS`/`XDR_ANALYTICS_BIOC` at T+30 min on the relay batch and
T+15 min on the bursts. Relay was the strongest ungated candidate over its native transport —
if it stays silent, collector type is NOT the gating factor and the Identity Analytics /
baseline question becomes the whole game. Watch window remains open.

**Standing conclusion update:** across every transport tried (CEF/syslog Exp 1–7, HTTP
collector Okta/GW/TAP, native WEC Exp 8–10), nothing fires analytics on this tenant. All roads
now point at tenant-side enablement: Identity Analytics toggle + Cloud Identity Engine pairing
(`pan_dss_raw` still 0 rows / 30 d).

## Exp 11 (2026-10-04 ~03:41 UTC): ungated network detectors via `panw/ngfw_traffic`

Scope decision: identity-gated detectors are blocked tenant-side (Identity Analytics off,
`pan_dss_raw` empty), so this round targets **module-free detectors only** — from the catalog,
524 ungated, of which the broker-feedable pools are: PAN traffic (44), PAN EAL (36),
third-party firewalls (23), PAN threat/URL (7), WEC (5), platform/health (13).

Live network feeds on the tenant: `panw_ngfw_traffic_raw` (10.7k rows/7d) and
`fortinet_fortigate_raw` (7.5k rows/7d); `panw_ngfw_threat_raw`/`_url_raw` empty (those
detectors need a threat/URL feed we have not started).

Eight workers fired (`scripts/experiments/exp11_network_ungated.py`, recipe copied from the
live baseline jobs):

| Worker | Detector | Window | Events |
|---|---|---|---|
| exp11-port-sweep | Port Sweep | 1 h | 40 (one host → 40 hosts :445) |
| exp11-smb-from-dc | Suspicious SMB connection from domain controller | single | 3 (DC 10.20.0.10 → WS :445) |
| exp11-torrent | A Torrent client was detected | single | 3 (app=bittorrent) |
| exp11-new-ftp-server | New FTP Server | single | 3 (untrust → 10.20.63.20:21) |
| exp11-large-upload | Large Upload (HTTPS) | 1 d | 8 × ~500 MB sessions |
| exp11-uncommon-ssh | Uncommon SSH session | single | 2 |
| exp11-weak-kerberos | Weakly-Encrypted Kerberos Ticket (single + 10-min multiple) | 10 min | 12 (kerberos → DC:88) |
| exp11-dcsync-net | Possible DCSync from a non domain controller (network) | single | 4 (ms-drsuapi/ms-rpc → DC) |

Landing verified in `panw_ngfw_traffic_raw` (per-source counts ≥ fired counts; some sources
overlap the baseline pool). Alert board: zero at T+12 min. Windows open: singles (fast),
sweep (1 h), large upload (1 d).

## Exp 12 (2026-10-04 ~04:00 UTC): PAN threat + URL feeds started, 6 ungated detectors fired

Both `panw_ngfw_threat_raw` and `panw_ngfw_url_raw` were empty; the bundle how_to_use gives the
CEF route (`panw`/`ngfw_threat`, `panw`/`ngfw_url`; never `ngfw_cef`, whose catch-all drops
non-matching events). Fired (`scripts/experiments/exp12_pan_threat_url.py`):

| Worker | Detector | Window |
|---|---|---|
| exp12-pastebin-nonbrowser | Non-browser access to a pastebin-like site | single |
| exp12-powershell-github | PowerShell Initiates a Network Connection to GitHub | single |
| exp12-nonbrowser-webui | A non-browser process accessed a website UI | single |
| exp12-tunnel-creation | Uncommon network tunnel creation (psiphon) | single |
| exp12-rmi-ldap-external | Rare connection via RMI-IIOP / LDAP to external | single |
| exp12-internal-vuln-threat | Rare Internal Firewall Vulnerability Threat Alert (internal→internal, high) | single |

Note: the module import in the job-seeding script re-ran the workers once — patterns fired twice
(harmless; doubles the signal). Landing verified: `panw_ngfw_url_raw` 28 rows, attack domains
6× each; `panw_ngfw_threat_raw` 6 rows. Alert board zero at T+10 min.

New baseline jobs: `baseline-url-trickle` (11 * * * *) and `baseline-threat-trickle`
(41 */2 * * *), Asia/Riyadh, benign shapes, so both datasets accumulate history.

**Open windows across the board:** Exp 11 singles (T+~40 min, silent), Port Sweep (1 h),
Large Upload HTTPS (1 d), Exp 12 singles (T+10 min). Hourly watcher armed.

## Exp 13–14 (2026-10-04 ~04:28–05:05 UTC): canary + deep multi-source attack story

**Worker API change noticed (stc-engine, deployed between 04:00 and 04:28 UTC):**
`xlog.create_data_worker` no longer accepts `duration_seconds`/`max_events`
(GraphQL `WorkerFakerInput` dropped them). New semantics: a worker emits `count` events spread
over `interval` seconds, one-shot, with a sustained ceiling of 10 events/s
(`count/interval ≤ 10` or it is rejected). Recurring jobs carrying the old args still run
successfully (compat path). Scripts updated accordingly.

**Canary (the control):** proven Port Scan shape (FortiGate CEF, 150 events, privileged ports,
SYN/RST) on two FRESH source hosts (192.0.2.99 external, 10.20.63.99 internal) — the exact
shape that fired in 3.5–12 min on 2026-08-31. **Silent at T+27 min**, past its historical
window. If the canary stays silent, the engine's current state (baseline maturity / enablement),
not our event shapes, is the blocker.

**Deep story (persona WS-STCE-21 / 10.20.63.21 / stc\k.alsayed; WEC side PHWS-021 /
k.alsayed@phantom.lab):** `exp13_deep_attack.py` — C2 beacon (90 events / 90 min heartbeat to a
rare external IP), recon sweep (100 events / 12 min, 50 hosts × privileged ports), lateral
SMB/RDP (30 / 45 min onto servers + DCs), exfil HTTPS (24 × ~100 MB / 60 min), exfil DNS
(30 / 30 min to odd resolver); plus slow-burn job `exp13-spam-bot-slow` (17 * * * *,
24 SMTP sessions/hour to many external servers, targeting the 3-day Spam Bot window).

**WEC deep batch:** `exp14_wec_deep.py` — 79 events, all landed (`_collector_type=WEC`):
kerberoast 20× 4769 RC4, relay 12× 4624 loopback, DCSync 4× 4662 + story, lockout storm
16× 4740 (10 distinct + 6 single-user), short-lived account 4720→4726, group add/remove
4728→4729, local group enum 8× 4798 + 7× 4799, LDAP admin enum 6× 1644 (Directory Service
channel, adminCount/memberOf filters), SMS Admins 4732, sensitive reset 4724.

**Heavy Okta rounds (gated, fired anyway for the record):** password_spray ×150,
failed_then_success ×80, mfa_fatigue ×60 → `okta_sso`; GW impossible_travel_login ×20 →
`google_workspace_drive_raw`.

**Alert board: zero** across all of it (canary T+27 min, WEC batch T+15 min, Okta T+5 min).
Watch continues via the hourly watcher; spam-bot and large-upload windows run for days.

## BREAKTHROUGH (2026-10-04 ~07:00 UTC): 16 analytics alerts fired — full mapping

**The board was never empty — the watcher query was.** `filter alert_source in (...)` on the
`alerts` dataset silently returns 0 rows while the alerts exist (verified: unfiltered fetch
shows them; `comp count() by alert_source` counts them). All ad-hoc checks before this point
used the broken filter. Correct pattern: fetch `dataset = alerts | fields ... | sort desc _time`
unfiltered and match client-side. The hourly watcher automation never used the broken filter,
but its name watchlist missed the Windows/identity families — watchlists extended
(dcsync/kerberos/lockout/delegation/guest/machine-account/etc.), seen-state reset, manual run
re-detected all 16 and pushed the notification.

| Alert | Severity | Exp | Payload | Host/User attribution |
|---|---|---|---|---|
| Machine account was added to a domain admins group | MEDIUM | Exp 8 | 4728 over WEC | PHDC02 / adm.malwadi |
| User added to a Windows privileged group | LOW | Exp 8/14 | 4728 WEC | PHDC02 / adm.malwadi |
| A user enabled the Windows default Guest account | LOW | Exp 9 | 4722 WEC | PHSRV-FS01 / adm.malwadi |
| User added to the SMS Admins local group | LOW | Exp 14 | 4732 WEC | PHSRV-FS01 / k.alsayed |
| Possible DCSync by an unusual user ×2 | LOW | Exp 8 + 14 | 4662 repl GUIDs over WEC | PHDC02 / phantom.repltest + k.alsayed |
| Abnormal issuance of weakly encrypted service tickets ×2 | LOW | Exp 10 + 14 | 4769 RC4 bursts over WEC | PHDC02 / svc.web + k.alsayed |
| Excessive user account lockouts | LOW | Exp 14 | 16× 4740 WEC | PHDC02 |
| Abnormal SMB activity to multiple hosts | LOW | Exp 11 | port sweep, panw traffic | WS-STCE-14 |
| Large Upload (HTTPS) ×2 | LOW | Exp 11 + 13 | panw traffic | WS-STCE-16 + WS-STCE-21 |
| An Uncommon SSH session to a rare IP | LOW | Exp 11 | panw traffic | WS-STCE-17 |
| Spam Bot Traffic | LOW | Exp 13 | panw SMTP job (fired on first hourly run, not 3 d) | WS-STCE-22 |
| Multiple Okta MFA requests, unusual characteristics | LOW | Okta mfa_fatigue | HTTP collector | noura.alharbi |
| Okta FastPass reported phishing attack suspected | LOW | Okta scenario | HTTP collector | fastpass.h.* |

**Conclusions this settles:**
1. **Transport is not the gate.** CEF/syslog (Exp 11/13), WEC (Exp 8–10/14) and HTTP collector
   (Okta) all fired. The syslog-era silence (Exp 1–7) was detector-gating, not transport.
2. **Windows analytics fire from WEC events crafted by `wec-sender.send_events`** — including
   custom-rendered non-catalogued ids (4662/4728/4732/4740/4769).
3. **Some identity-flavored detectors fire without visible CIE rows** (DCSync, Okta MFA/FastPass
   fired as XDR_ANALYTICS_BIOC). The "all identity detectors are off" conclusion was too broad.
4. **Persona attribution works end-to-end**: alerts carry our synthetic hosts/users, so the
   engine read exactly the entities we crafted.
5. Windows detectors that did NOT fire yet: relay (4624 loopback), LDAP enum (1644), 4781
   rename, 4742 SPN/delegation, 4616 time change, 4724 reset, 4720/4726 pair — either
   baseline-gated or shape-tuning needed.

## Exp 15 (2026-10-04 ~07:10 UTC): shape variants for the unfired detectors

`scripts/experiments/exp15_wec_unrefired.py` — 44 events over WEC, each variant on a distinct
user/host so any alert attributes the winning shape:

- **Kerberos relay ×4 variants**: literal 127.0.0.1 loopback; Kerberos package (not NTLM);
  DC self-relay (logon on PHDC02 from its own IP); machine account relayed onto itself.
- **LDAP admin enum heavier**: 15× 1644, visited-entries 28450, adminCount/memberOf filters for
  Domain Admins / Enterprise Admins / Schema Admins / Account/Backup Operators.
- **sAMAccountName spoof full sequence**: 4781 rename PHWS-115$ → PHDC02$, 4768 TGT request for
  the spoofed name, rename back.
- **4742 complete shapes**: SPN-cleared with Previous/New Value blocks; delegation change with
  cifs/ldap AllowedToDelegateTo.
- **4616 on the DC** (6-day delta), **4724 ×3** reset attempts on adm.malwadi,
  **short-lived tmp.deploy77** (4720→4726 three minutes apart), **4662 System Management
  Container** access (#53), **4768 PKINIT** with full certificate fields (#26),
  **single-account lockout storm** 12× 4740 on svc.monitoring (#16).

Alert board: no new analytics alerts at T+30 min on the earliest variants. The day's firing
latencies were 0–25 min, so these shapes are likely not what those detectors read — next lever
is per-detector documentation research (exact event/field requirements) rather than more
variants. The hourly watcher (watchlist now covers the full Windows/identity family) will catch
any late arrivals.

## Exp 16 (2026-10-04 ~09:25 UTC): catalog-informed retry of the unfired set

`scripts/experiments/exp16_relay_and_unfired.py` — 14 WEC events + 4 PAN traffic workers,
shapes derived from the detector catalog (`docs/research/analytics-detector-catalog-2026-09-30.json`):

- **Kerberos relay WITH the new-machine story** the docs hint at: 4741 creates machine account
  `PHWS-RELAY$` (subject `relay.operator`), then a 4624 type-3 Kerberos logon for `PHWS-RELAY$`
  on PHSRV-FS01 from 127.0.0.1.
- **sAMAccountName rename missing the trailing `$`**: 4781 `PHWS-210$` → `PHWS-210`
  (Exp 15 renamed *to* a `$`-suffixed DC name — catalog says the detector keys on the *missing* `$`).
- **SPNs cleared**: 4742 SPN-cleared on `PHSRV-SQL02$` + a 5136 Directory Service Changes
  variant (servicePrincipalName, "Value Deleted").
- **Sensitive password resets on built-in sensitive accounts**: 4724 → `Administrator` (-500)
  and `krbtgt` (-502), subject `helpdesk.temp` (Exp 15 targeted a custom admin).
- **System Management Container**: 4662 read (mask 0x10) by non-admin `sccm.recon`.
- **Multiple user deletions**: 6× 4726 (`tmp.sweep00–05`) inside 1 h.
- **NTLM Relay / Machine Account NTLM Relay** (PAN traffic, 10 min): same user
  `stc\relay.victim` and machine `PHSRV-APP02$` each seen from two source IPs.
- **Kerberos User Enumeration** (Medium, 1 h) and **Kerberoasting without SPNs**: kerberos-app
  traffic bursts to the DC (best effort — CEF traffic cannot express principal-unknown error
  codes or SPN types).

**Verification:** every WEC event confirmed ingested *and* modeled into XDM
(`datamodel dataset = microsoft_windows_raw`; note `xdm.event.original_event_type` carries the
task-name string like `User Account Management`, not the numeric event ID — a numeric filter
returns nothing). The 1644 LDAP path was also re-confirmed dead: 1644 events land in
`microsoft_windows_raw` but produce zero XDM rows, so no LDAP-content detector can fire over
WEC until the Directory Service channel gets parsing/modeling coverage.

**Result (board checked at +25 min and again after all test windows closed):**

| Detector | Shape | Result |
|---|---|---|
| A user deleted multiple users for the first time (Low) | 6× 4726 | **FIRED** (~10 min latency) |
| Possible Kerberos relay attack | 4741 + 4624 loopback for new machine | no alert |
| Suspicious sAMAccountName change | 4781 rename dropping `$` | no alert |
| SPNs cleared from a machine account | 4742 + 5136 | no alert |
| Sensitive account password reset attempt | 4724 → Administrator / krbtgt | no alert |
| Suspicious access of the System Management Container | 4662 read, non-admin | no alert |
| NTLM Relay / Machine Account NTLM Relay | PAN traffic, 2 source IPs | no alert |
| Kerberos User Enumeration / Kerberoasting w/o SPNs | PAN kerberos bursts | no alert |

**Interim conclusion:** ingestion and modeling are now provably sufficient — the remaining
unfired detectors are suppressed upstream of the alert surface. Most likely causes: (a) the
detectors are Identity Analytics / Identity Threat Module gated and those modules stay inactive
without their own profile-building feeds; (b) the network detectors key on telemetry that CEF
traffic logs cannot carry (NTProofStr duplication, Kerberos error codes, SPN types — these come
from the firewall's EAL/auth telemetry or the XDR agent, not synthetic syslog). The firing set
(DCSync, weak tickets, lockouts, group adds, SMS Admins, Guest, SMB sweep, Large Upload, Spam
Bot, uncommon SSH, Okta MFA/FastPass, multi-delete) is consistent with "single-event or simple
aggregate detectors over fully modeled fields".

## Corrections and replays (2026-10-04 ~10:30 UTC, skills round)

Written while turning every fired alert into a skill (issue #66). Each Windows recipe was replayed exactly as written, with a new actor and new RIDs each time (ledger rows `E19_wec_skill_replay`, `tooling/analytics-lab/skill_replay_wec.py`).

1. **Suspicious sAMAccountName change DID fire** (alert 11217, Low, from the Exp 16 4781 `PHWS-210$` to `PHWS-210`, 12 seconds after the send). The Exp 16 table above records it as "no alert"; the alert is on the tenant (arrived 09:25:59Z). The alert text names the missing trailing `$`, which is the detection. Renames *to* a DC's name with the `$` kept (Exp 9 and 15) are the ones that stayed silent.
2. **Replay results, all as written:** machine account to Domain Admins, user added to a privileged group (with a *user* as the member; the machine-account alert did not fire for it), DCSync, Guest enabled, SMS Admins, weak service tickets (19 SPNs), lockouts (caller host `PHWS-567`: the alert reported that host), sAMAccountName and multiple deletions all fired again, **9 of 9**, 16 seconds to 1.7 minutes after the send. Alert latency for the WEC set is seconds to minutes, not the 25 minutes the first write-ups assumed.
3. **Conclusion 1 of the BREAKTHROUGH section needs a limit.** "Transport is not the gate" holds for Okta (HTTP) and the firewall detectors (CEF); it does **not** hold for the Windows identity detectors. The same event families sent over syslog/CEF (Exp 2-6) landed, modeled and raised nothing; over WEC (Exp 8-10, 14, 16) the corresponding detectors fired. The Windows detectors read the Windows event-log pipeline that only WEC or the XDR agent feed (memory note `detector-feed-vs-dataset`).
4. **Lockouts:** in a real 4740 the `TargetDomainName` field is the *caller computer name*. Exp 14 wrote the domain `PHANTOM` there and the alert said "originated from host PHANTOM"; the replay wrote a workstation name and the alert reported it. Use a new caller host per run.
5. **Okta MFA bombing needs no Tor exit and no hand-built JSON:** `http-sender.generate_events` with `failed_then_success` (30 events, 900 s) and then `mfa_fatigue` (25 events, 600 s) for one baseline user fired the alert on 2026-10-03 (`noura.alharbi`) and again as a replay on 2026-10-04 (`reem.aldosari`).

## Exp 17 (2026-10-04 ~14:50 UTC): account-lifecycle + Kerberos detector batch over WEC

`scripts/experiments/exp17_account_lifecycle.py` — 13 detector families in one `send_events`
call (~60 events), shapes taken from the detector catalog, distinct personas per variant:
hidden `$`-suffixed user (Medium), default-local-account masquerade (DefaultAccount + Guest —
Exp 9 used "Administrator", which the doc does not list), 6× rare-account creations, group
add-then-remove with the add backdated 9 h (10 h window), 8× AS-REP 4768 with PreAuthType 0,
15× AES 4769 service tickets (contrast to the RC4 weak-ticket detector), dNSHostName changed to
the DC's name (Medium), AdminSDHolder WRITE_DAC 4662, SID History 4765, computer promoted to DC
(UAC 0x82000), rare machine account creation, unusual account unlock 4767, and a 10× 4799 local
group enumeration burst on a fresh host.

**Blocked at fire time:** the gcloud IAP tunnel to stc-engine dropped and the account needs
interactive re-authentication (`gcloud auth login`). Script committed; fire on re-auth.

## Recurring jobs keep producing (board snapshot 2026-10-04 ~14:55 UTC)

The hourly/daily pressure jobs with rotating personas are re-firing the proven families
continuously: weak tickets (`adm.rpw1`), multi-delete (`adm.rpx1`), lockouts, SMS Admins
(`adm.rps1`), SMB sweep (WS-STCE-12), Large Upload HTTPS (WS-STCE-13), Spam Bot (WS-STCE-41),
Okta MFA (reem.aldosari), and one **new family: `Failed Connections` (Low, WS-LEGAL-07 /
hana.alsaud)** — covered by the existing `trigger_failed_connections_alert` skill.
