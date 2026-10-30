# WEC detector pick list — 2026-10-03

Selection from the 58 Windows/WEC-reading analytics detections, chosen for craftability with
synthetic events: single-event or short-window (≤3 h) count detectors, no baseline dependency,
Security-channel events we can fully control. Each pick lists the events to build, the
load-bearing fields, and the reference simulator recipe to copy (`refsim/refsim-main/modules/windows_events.py`,
`_THREAT_GENERATORS`).

Entity strategy for all: fresh accounts/hosts per run (avoid history-based suppression),
domain `PHANTOM` / `phantom.lab`, DC `PHDC02.phantom.lab`, RID range 3100+ for synthetic users,
machine accounts `PHWS-1xx$`. Timestamps must be current (detector windows are evaluated on
`_time`).

## Priority 1 — single-event, highest confidence

| # | Detection | Events to build | Load-bearing content | reference simulator recipe |
|---|---|---|---|---|
| 17 | Machine account added to domain admins (Medium) | 1× 4728 or 4756 on DC | Target group `Domain Admins` (SID …-512), member name ends in `$` | `machine_account_to_domain_admins` |
| 27 | dNSHostName change to DC name (Medium) | 1× 5136 (or 4742) | Computer object's dNSHostName set to a real DC's FQDN (`PHDC02.phantom.lab`) | `dnshostname_spoofing` |
| 30 | Suspicious sAMAccountName change (Low) | 1× 4742 | Old→new sAMAccountName, esp. machine renamed with/without trailing `$` | `samaccountname_spoofing` |
| 31 | SPNs cleared from machine account (Low) | 1× 4742 | ServicePrincipalName values deleted in message text | hand-build |
| 32 | Computer promoted to DC (Low) | 1× 4742 | userAccountControl gains SERVER_TRUST_ACCOUNT (0x2000); message shows new UAC value | hand-build |
| 33 | User account delegation change (Info) | 1× 4742/4738 | msDS-AllowedToDelegateTo set, or TrustedForDelegation flag | `delegation_change` |
| 35 | SID History added (Info) | 1× 4742 or 5136 | sIDHistory populated with foreign-domain SID | hand-build |
| 36 | Key credential attribute modification (Info) | 1× 5136 | Attribute = msDS-KeyCredentialLink, DN of a user object | hand-build |
| 37 | AdminSDHolder ACL modification (Low) | 1× 5136 | Object DN `CN=AdminSDHolder,CN=System,DC=phantom,DC=lab`, DACL change | hand-build |
| 2 | Masquerading as default local account (Low) | 1× 4720 (member server, not DC) | New local account named `Administrator`/`Guest` with non-default RID | hand-build |
| 3 | Default local account enabled (Info) | 1× 4722 | Target `Guest` or `Administrator` | `default_account_enabled` |
| 13 | Password never expires (Info) | 1× 4738 | Message contains "Don't Expire Password - Enabled" | hand-build |
| 14 | Sensitive account password reset (Info) | 1× 4724 | Target = privileged account (`adm.*`), subject = non-admin | hand-build |
| 26 | PKINIT TGT request (Info) | 1× 4768 | Certificate Issuer/Serial/Thumbprint fields populated | hand-build |
| 56 | System time changed (Info) | 1× 4616 | Previous/new time fields | hand-build |
| 40 | Potential DCSync by unusual user (Info) | 2× 4662 (+4624 story) | Replication GUIDs 1131f6aa/…ad/…ae, 89e95b76, mask 0x100, subject NOT a DC | `dcsync` (our Exp 2 recipe, now via WEC) |

## Priority 2 — short-window count detectors (burst in one run)

| # | Detection | Events to build | reference simulator recipe |
|---|---|---|---|
| 22 | Multiple service tickets (Info, 10 min) | 15–20× 4769, one user, distinct SPNs | `multiple_service_tickets` |
| 23 | Weakly encrypted service tickets (Info, 10 min) | 15–20× 4769, TicketEncryptionType 0x17 (RC4) | our Exp 3 recipe |
| 24 | TGT requests to irregular service (Low, 10 min) | 10× 4768 burst, one user | `irregular_tgt_burst` |
| 25 | TGT without pre-auth (Info, 10 min) | 8–10× 4768, Pre-Authentication Type 0, distinct users | hand-build |
| 4 | Multiple suspicious accounts created (Low, 1 h) | 5–8× 4720 distinct odd names, one subject | `suspicious_account_creation` |
| 5 | Short-lived account (Low, 1 h) | 4720 then 4726 same account, ~5 min apart | hand-build (two-phase) |
| 6 | Multiple accounts deleted (Info, 1 h) | 5–8× 4726 | `mass_account_deletion` |
| 15 | Excessive lockouts (Low, 1 h) | 10+× 4740, distinct users | `account_lockout` |
| 16 | Single account lockouts (Info, 1 h) | 8+× 4740, same user | `account_lockout` (single-user) |
| 20 | Added then removed from group (Info, 10 h) | 4728 then 4729 same user+group, minutes apart | `priv_group_add_remove` |
| 21 | SMS Admins addition (Low, 3 h) | 1–2× 4732, local group `SMS Admins` | `sms_admins_addition` |
| 52 | Local group enumeration (Info, 5 min) | 20× 4798/4799 burst, one host | hand-build |
| 51 | Admin groups enumerated via LDAP (Info) | 5–10× 1644, admin-group filters | our Exp 4 recipe, retried over WEC |
| 28/29 | Spoofed sAMAccountName tickets (Medium) | 4742 rename to non-`$`, then 4768/4769 for it, rename back | `samaccountname_spoofing` (multi-stage) |

## Priority 3 — deferred

- **G (41–47, AD CS):** events 4886–4899 come from the Certification Authority channel —
  verify wec-sender can emit non-Security channels and that the WindowsEvents parsing rules
  ingest that provider before building.
- **H (48–50, Exchange):** event source uncertain; skip until G is proven.
- **1, 7–12, 34, 38, 39, 53–55, 57, 58:** rarity/baseline-gated ("rare", "unusual", "abnormal")
  or meta-detectors — low yield for synthetic firing now.

## Pack status (verified 2026-10-03 via `datamodel` XQL)

`microsoft_windows_raw`, `okta_sso_raw`, `proofpoint_tap_raw`, `google_workspace_drive_raw`
are all XDM-modeled — the needed packs are active. No installs required for P1/P2. AD CS (G)
is the only theme that might need an extra pack; test one 4886 before investing.
