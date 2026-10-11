---
name: simulate_identity_telemetry
displayName: Simulate identity + authentication telemetry (Windows, Duo, AD)
category: workflows
description: 'Generate authentication and identity telemetry — Windows Security events (4624/4625/4768/4769/4771/4672/4616/1644), Duo MFA, Active Directory — into Cortex XSIAM over CEF, so that user-to-machine attribution actually lands in the data model. Use when the operator asks for logon activity, "who logged into which machine", MFA denials, password spray, Kerberoasting, impossible traveller, LDAP enumeration, or any identity/ITDR scenario. Encodes the result of reverse-engineering the rules: which rule version is authoritative, which fields are gates, why the `message` string is load-bearing on Windows, the coalesce-pinning trap, and which analytics detectors are actually reachable versus permanently gated.'
icon: passkey
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Simulate identity + authentication telemetry

## When this skill applies

The operator wants **authentication or identity** activity, in any of these shapes:

- *"Show me who logged into which machine."* / *"Generate Windows logon events."*
- *"Simulate a password spray."* / *"Make it look like Kerberoasting."*
- *"I need MFA denials."* / *"Push bombing."* / *"An impossible traveller."*
- *"Generate AD enumeration."* / *"Someone sweeping admin groups over LDAP."*
- *"Give me ITDR data."* / *"Identity threat telemetry."*

Route elsewhere when the ask is a generic vendor stream with no identity angle
(`stream_simulate_to_xsiam`), or verification of an existing run
(`xdr_verify_simulation_telemetry`).

---

## The single most important thing: check the rule VERSION first

A content pack ships several modeling-rule versions, each scoped by tenant version, and only one
is live. Reading the wrong one wastes a whole cycle and the failure is silent — the events land,
they map, and a subtree you expected simply is not there.

```
MicrosoftWindowsEvents_1_3    fromversion 8.2.0  toversion 8.14.0
MicrosoftWindowsEvents_2_11   fromversion 8.15.0 (none)          <- live on >= 8.15

DuoModelingRule_1_3           6.10.0 - 8.3.0
DuoModelingRule_2_0           8.4.0  - 8.14.0
DuoModelingRule_2_11          8.15.0 - (none)                    <- live on >= 8.15
```

The `_2_11` versions add an entire `xdm.source.identity.*` mirror (username, upn, identifier,
groups, sam_account_name, first/last name, user_type) that earlier versions lack. **If that
subtree populates, the tenant is >= 8.15** — which is a free way to confirm the version without
an API call.

Read the versions from the `.yml` beside each `.xif`, never from a filename guess.

---

## Which source to reach for

| Goal | Source | Why |
|---|---|---|
| "user X logged into machine Y" | **Windows** `microsoft_windows_raw` | maps `xdm.source.user.username` + `xdm.source.host.hostname` + `xdm.logon.type` + `xdm.event.operation = AUTH_LOGIN` |
| An **authentication story** / `auth_identity` | **Duo** `duo_duo_raw` | the ONLY bound source that emits both `EVENT_TAG_AUTHENTICATION` and `xdm.source.user.upn` |
| Impossible traveller, MFA fatigue, SSO resource abuse | **Duo** | it carries `access_device.location.*`; Windows has no geo |
| **Cloud SSO** identity analytics (Entra): TOR sign-in, SSO brute force, impossible traveler | **Entra ID** `msft_azure_ad_raw` | sign-in logs carry geo + status.errorCode + CA result; use the `trigger_identity_analytics` skill — its 26-field schema is proven |
| AD enumeration, Kerberos, privilege escalation | **Windows** | 1644 LDAP search, 4768/4769/4771 Kerberos, 4728 group add |

**Windows cannot build an authentication story.** Its rule maps 11 of the 12 fields Cortex
documents as mandatory but never sets `xdm.source.user.upn`, and fills `xdm.event.tags` with
`arraycreate(execution_name)` instead of the auth tag. That is a property of the rule, not
something a better event fixes. It still supports full XDM normalization, XQL, dashboards and
correlation rules.

---

## Windows: the gate set

An event must clear THREE filters. Miss the first and it is discarded with **no trace** — no
dataset row, no error row, not even `unknown_unknown_raw`.

```
PARSE  MicrosoftWindowsEvents.xif   no_hit=drop
  filter to_string(time_created) ~= ".*\d{2}:\d{2}:\d{2}.*"
    AND provider_name not in (Sysmon, "AD FS Auditing", AMSI, DNSServer, DNS-Server-Service)

PARSE  MicrosoftCommonParsingRules.xif   no_hit=keep      <- the only catch-all
  filter time_created != null

MODEL  MicrosoftWindowsEvents_2_11.xif
  filter channel in ("System","Application","Directory Service")
      or provider_name in (PowerShell, TaskScheduler, Firewall, Defender, ActiveDirectory_DomainService)
      or provider_name contains "Microsoft-Windows-Security-"
```

**`Security` is deliberately NOT in the channel list.** Every 4624/4625/4768/4769 enters through
the third disjunct only, which is why `provider_name = "Microsoft-Windows-Security-Auditing"`
matters more than `channel` here — and why setting `channel = "Security"` is safe rather than
something to fake around.

Choosing `channel: Security` does kill every `if(channel="System", …)` branch, ruling out
`event_data.HostName`, `.DCName`, `.ProcessID`, `.Module` and the `param1/2/3` family for that
event. Correct trade; just do not then try to seed them.

**Back-dating**: `time_created`, ISO-8601 with a literal `T` and `Z`. The rule parses
`%FT%H:%M:%E*SZ` and sets `_time` to the EARLIEST of (`time_created`, `_insert_time`, `_time`),
so a past value wins. An epoch integer does NOT work on this field.

---

## Windows: `message` is load-bearing, not decoration

**The rule runs 42 `regextract()` calls over `message`, feeding 33 distinct fields**, and several
have NO other source anywhere in the rule. A generic message silently kills a third of the
mapping surface.

```
"Failure Code: 0x18"     -> xdm.auth.kerberos_tgs.error_code = ERR_KDC_PREAUTH_FAILED
"Failure Reason: ..."    -> xdm.event.outcome_reason
"Process Name: ..."      -> xdm.source.process.executable.path and .name
"Member: ... Account Name: ..."  -> xdm.target.user.ou   (4728/4729)
```

There is no `event_data.FailureCode` leaf. **The entire Kerberos error taxonomy — password spray
included — is unreachable unless the prose is right.** Write real multi-line Windows message
bodies; tabs are significant, because several regexes terminate a capture on the tab run.

The CEF key must be literally `message`, not `msg`.

---

## Duo: the gate is `eventtype`, and there are three blocks

```
filter eventtype = "authentication"    58 xdm assignments   <- the identity story
filter eventtype = "administrator"     14                   <- admin console actions
filter eventtype = "telephony"          6
```

They read DIFFERENT columns. `username`, `action`, `object` and the `description.*` leaves belong
to the administrator block; the authentication block uses `user.name` and the `application`
composite. Case matters too: authentication reads lowercase `host`, the other two read `HOST`.

**Duo ships NO parsing rule.** Routing is purely derived (`vendor=duo product=duo` ->
`duo_duo_raw`), and nothing derives `_time` from the body — so the **CEF `rt` epoch integer is
the only back-dating handle**. An ISO string is ignored there. (Note the asymmetry with Windows,
where ISO is required and epoch is ignored.)

**Two devices, two subtrees** — this is what makes Duo worth using:

| composite | meaning | subtree |
|---|---|---|
| `access_device` | machine authenticated FROM | `xdm.source.*` |
| `auth_device` | device that ANSWERED the prompt | `xdm.intermediate.*` |
| `application` | what they authenticated TO | `xdm.target.resource.*` |

The rule blanks `xdm.target.ipv4`/`ipv6`, so the **machine is always on the SOURCE side**.

---

## Traps that produce a plausible WRONG result

**Pin every member of a coalesce, not just the one you want to win.** The generator synthesises a
random value for any DECLARED field left unpinned, and a synthesised value EARLIER in the chain
beats the real one behind it:

```
user_sid = coalesce(event_data -> SID, event_data -> SubjectUserSid, user -> identifier, ...)
     pinning only SubjectUserSid  ->  xdm.source.user.identifier = "hL42dIss"
```

**Declare the SMALLEST field set that works.** A full-schema override drags synthesised noise
into the record — for example on a Windows logon: target geography in Bulgaria, an OVH ASN,
`xdm.target.file.path = /usr/bin/curl`. Use 27-42 fields per event ID, and DROP logon-only fields
(`LogonType`, `AuthenticationPackageName`, `LogonProcessName`, `ElevatedToken`, `Status`) on
Kerberos event IDs or `xdm.logon.type` falls through to the raw synthesised string.

**A higher field count can mean a WORSE result.** A noisy full-schema run can score 77 xdm fields while
the correct minimal run scores 58. Never use field count alone as the quality signal — scan 25
rows for values that look generated (8-char mixed-case tokens, geography that does not belong).

**Bind identity per record.** The message embeds the user and host, so it cannot vary
independently of them. Render the message INSIDE the per-identity entity group alongside that
identity's leaves. Parallel lists produce a cartesian smear where the prose contradicts the
structured fields.

**Underscore-prefixed columns are broker-owned.** Duo's rule assigns `xdm.event.id = _id`, but the
broker stamps `_id` and overwrites anything sent. `txid` on the same event survives.

**Array accessors cannot be satisfied through a dotted leaf.** Duo's `user -> groups[]` always
comes back as `['"…"']` because the generator serialises every leaf as a JSON string. Send one
group name; a true multi-value array is not reachable.

**`email` must be `first.last@domain`** — Duo's rule splits it to derive first/last name.

**Windows `event_result` is case-sensitive**: exactly lowercase `success` / `failure`. Anything
else falls through the coalesce and `xdm.event.outcome` lands as an uncoerced raw string — a
4771 without it shows `outcome = 0x18` (the raw failure code) instead of `FAILED`.

**`event_action` is a poison pill on Windows** — arm 1 of the `event_type` coalesce, never
overwritten, so sending it destroys the canonical_task taxonomy.

---

## Verifying a run

**Do NOT `sort desc _time`.** Every back-dated run occupies the same window, so newest-by-`_time`
is a random draw across all of them and a corrected run reads as still-broken. Discriminate on a
value unique to the run — a pinned `process_pid`, a `record_id` range, a marker `txid`.

Mirror-image trap: filtering on a field set to a GENUINE vendor value (the real Microsoft
Security-Auditing provider GUID) matches the tenant's REAL agent data rather than the synthetic
events.

```
datamodel dataset = <ds> | filter <run-unique marker> | fields xdm.* | limit 25
```

Count distinct non-null `xdm.*` across >= 20 rows and take the union — any single row is sparse.

---

## What identity data can and cannot trigger

Set expectations before promising analytics. Across the 57 Windows and 21 Duo detector
pages in the Cortex documentation:

| Source | ungated | Identity Threat Module | Identity Analytics | reachable |
|---|---|---|---|---|
| Windows Event Collector | 5 | 3 | 49 | **8** |
| Duo | 0 | 1 | 20 | **1** |

- **Ungated** — runs on the base analytics engine. Reachable with synthetic logs.
- **Identity Threat Module** — needs the ITDR licence. Reachable when licensed.
- **Identity Analytics** — needs a Cloud Identity Engine directory-sync pairing that populates
  `pan_dss_raw`. **No volume or quality of synthetic logs satisfies this**, and `pan_dss_raw`
  cannot be seeded. Do not promise these.

The two ungated Windows detectors reachable from Security events are
`administrator-groups-enumerated-via-ldap` (1644) and `possible-kerberos-relay-attack`, both
**Test Period: N/A (single event)** — one well-shaped event can fire them.

**Synthetic CEF DOES drive XDR analytics** — XDR_ANALYTICS alerts carry
`original_tags: ['DS:Fortinet/FortiGate']` when driven by a synthetic FortiGate feed. So a
non-firing identity detector is a detector-availability problem, not a delivery problem. When the
goal is analytics VOLUME rather than an identity story, third-party firewalls are the better
surface — 23 of 23 of their detectors are ungated.

**Reading which source drove an alert**: `dataset = alerts | fields original_tags` — the
`DS:<vendor>/<product>` tag names it.

---

## Realistic scenario shapes

The per-field recipes live in each source's
`how_to_use`, which is the authority — read it with `data_sources_get_schema` rather than
reinventing the values.

| Scenario | Source | Shape |
|---|---|---|
| user-to-machine baseline | Windows 4624 | LogonType 2/3/10, identity bound 1:1 to a workstation |
| password spray | Windows 4771 | ONE source IP, many users, `Failure Code: 0x18` in the message |
| brute force | Windows 4625 | one user, one source, repeated, `Failure Reason:` prose |
| Kerberoasting | Windows 4769 | `TicketEncryptionType 0x17` (RC4) against a `0x12` (AES256) baseline, service SPNs |
| AD enumeration | Windows 1644 | `param2` swept across admin-group filters from one client |
| system-time change | Windows 4616 | single event, ITDR-gated |
| MFA fatigue | Duo | one user, one app, burst of `reason=no_response` denials then a success |
| impossible traveller | Duo | same identity, far-apart `access_device.location.country` |
| unusual SSO resources | Duo | NARROW baseline of 2 apps over 30 days, then 12 never-seen apps inside one hour |

The last one is worth calling out: a burst alone proves nothing. The detector compares against a
profile, so the **contrast** is the deliverable — generate the boring baseline first.
