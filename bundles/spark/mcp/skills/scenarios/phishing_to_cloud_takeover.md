---
name: phishing_to_cloud_takeover
displayName: Phishing cloud takeover
category: scenarios
description: 'Six-stage external-to-cloud chain — the full arc from inbox to cloud IAM persistence. Phishing email delivers a credential-harvest URL → user clicks (proxy logs the GET) → stolen creds replayed at the SaaS sign-in (impossible travel) → attacker grants OAuth consent to a malicious app → inbox forwarding rule exfiltrates mail + bulk download from cloud storage → attacker pivots the SaaS foothold into cloud IAM, creating a service-account key for persistent access. Vendor-agnostic — agent resolves vendor/product from the operator''s installed data sources at runtime. Triggers 7 XSIAM rules: Phishing email with malicious attachment, Malicious file download via proxy, Impossible Travel, OAuth Consent Grant Abuse, Mailbox Forwarding Rule Abuse, Data exfiltration to personal cloud storage, Cloud IAM Key Creation.'
icon: phishing
source: platform
loadingMode: on-demand
locked: false
attack:
  - 'TA0001: Initial Access (T1566.002 Spearphishing Link, T1078.004 Cloud Accounts)'
  - 'TA0006: Credential Access (T1078 Valid Accounts, T1528 Steal Application Access Token)'
  - 'TA0003: Persistence (T1098.005 Device Registration, T1098.003 Additional Cloud Roles, T1098.001 Additional Cloud Credentials)'
  - 'TA0010: Exfiltration (T1567.002 Exfiltration to Cloud Storage, T1114.003 Email Forwarding Rule)'
---

# Skill: Phishing → Credential harvest → Cloud takeover

## Category

scenarios

## Attack Type

Cloud-account takeover via consent-phishing tradecraft. Models the OAuth-grant abuse pattern that bypasses MFA entirely (the user authorizes the attacker's app legitimately; no password is ever guessed at the OAuth side). Most common variant: BEC actors and nation-state operators alike use this against M365 / Workspace tenants because the attacker keeps access even after the user rotates their password. The chain now runs all the way into cloud IAM: once the attacker has the SaaS foothold, they pivot into the user's cloud-platform privileges and mint a long-lived service-account key — a backdoor that survives the password reset too.

## MITRE ATT&CK Tactics

- TA0001: Initial Access (T1566.002 Spearphishing Link, T1078.004 Cloud Accounts)
- TA0006: Credential Access (T1078 Valid Accounts, T1528 Steal Application Access Token)
- TA0003: Persistence (T1098.005 Device Registration, T1098.003 Additional Cloud Roles, T1098.001 Additional Cloud Credentials)
- TA0010: Exfiltration (T1567.002 Exfiltration to Cloud Storage, T1114.003 Email Forwarding Rule)

## XSIAM analytics rules triggered

| # | Rule | Stage that fires it |
|---|---|---|
| 9 | Phishing email with malicious attachment / link | Stage 1 |
| 8 | Malicious file download / suspicious URL via proxy | Stage 2 |
| 4 | Impossible Travel | Stage 3 |
| 10 | OAuth Consent Grant Abuse | Stage 4 |
| 11 | Mailbox Forwarding Rule Abuse | Stage 5 |
| 20 | Data Exfiltration to Personal Cloud Storage | Stage 5 |
| 17 | Cloud IAM Key Creation (suspicious identity) | Stage 6 |

## Data classes used

| Stage | Data class | Why | If missing from stack |
|---|---|---|---|
| 1 | `email-gateway` | Email arrival + URL/attachment metadata | Required — stage cannot run; consider skipping Stage 1 and starting at Stage 2 (proxy click) |
| 2 | `proxy` | URL fetch by the user | Required for the click visibility; substitute with `firewall` if proxy missing (reduces fidelity) |
| 3 | `saas` (M365 or equivalent) | Sign-in event with country | Required — OAuth abuse requires the cloud audit log |
| 4, 5 | `saas` | OAuth consent + inbox rule + bulk download | Required |
| 5 | `proxy` + `firewall` | Egress to personal cloud storage | Use whichever the operator's stack has; ideally both |
| 6 | `cloud` | SaaS-to-IaaS pivot: service-account creation + key mint | If missing, end the chain at Stage 5 with a note that the cloud pivot would fire if cloud audit was instrumented |

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

Call `data_sources_installed_as_vendors`. Group `vendors[]` by `data_source_class` into the category lookup. If `email-gateway` AND `saas` are both missing, stop and tell the operator — there's no way to model this attack without at least one installed data source in each class. If only `proxy` is missing, fall back to firewall east-west denials at the proxy port (less fidelity but workable).

## Narrative thread

- **Phishing sender (Stage 1):** `invoice-portal@billing-secure-update.tk` (typo-squat domain on `.tk`)
- **Phishing landing URL (Stage 1, 2):** `https://billing-secure-update.tk/login.aspx?ref=invoice-Q4`
- **Target user:** `m.patel@corp.example` (claims processing manager, normal sign-ins from `GB`)
- **Target user IP (normal baseline):** `86.150.42.18` (residential UK)
- **Stolen-creds replay source IP (Stage 3):** `91.243.59.108` (RU — unusual for this user)
- **Malicious OAuth app (Stage 4):** `InvoicePro Sync` — sounds plausible for a finance user
- **OAuth client_id:** `8ba2f3d4-9c47-4a91-b81e-22f3ec9d4a7e`
- **Inbox forward target (Stage 5):** `m.patel.archive@protonmail.com` (attacker-controlled mailbox)
- **Bulk-download target (Stage 5):** OneDrive folder `Q4-Claims-Documents` (~120 files)
- **Cloud project (Stage 6):** `gcp-prod-ExampleCorp`
- **Cloud SA created (Stage 6):** `data-export-svc@gcp-prod-ExampleCorp.iam.gserviceaccount.com`
- **Cloud SA key ID (Stage 6):** `8f3a91d2c4b7e5a8d6f9b2c1e4a7d3f5b8c2e9a1`
- **Wall-clock time:** Stage 1 = single email (instant). Stage 2 ~3 min after delivery. Stage 3 ~8 min later. Stage 4-5 within 5 min of Stage 3 success. Stage 6 ~8 min after Stage 5.

**Stage 6 narrative note:** the target user above (`m.patel`, claims processing manager) is chosen for
plausibility through Stage 5 — a finance-adjacent role is exactly who consent-phishing and mailbox-rule
abuse target. Stage 6 assumes this user (or the account the attacker has landed in) also carries cloud
platform privileges — realistic in orgs with IAM over-provisioning, but if your test tenant's `m.patel`
equivalent genuinely has no cloud access, retarget Stage 6 at a user who does (a devops/platform-engineer
persona) rather than straining the story. The recipe itself is identity-agnostic.

---

### Stage 1 — Phishing email delivered (1 high-priority + 49 noise events) — ~50 events over 60 seconds

The malicious email lands. Generate ~49 noise events (legitimate marketing, partner emails, internal newsletters) so the signal isn't trivial; the malicious one is a single CEF entry with the credential-harvest URL.

**Data class:** `email-gateway`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[email-gateway].vendor>
  product: <stack[email-gateway].product>
  count:    50
  interval: 1
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    senderEmail:    ["partners@example-supplier.com", "newsletter@industry-news.io",
                      "noreply@hr-internal.corp.example", "alerts@payroll-svc.corp.example",
                      "invoice-portal@billing-secure-update.tk"]
    recipientEmail: ["m.patel@corp.example", "team-finance@corp.example",
                      "all-employees@corp.example"]
    emailSubject:   ["Q4 Newsletter", "Project status update",
                      "Re: Payment terms", "Quarterly summary",
                      "URGENT: Invoice #INV-Q4-2891 Action Required"]
    request:             ["https://example-supplier.com/portal",
                      "https://industry-news.io/articles/12",
                      "https://billing-secure-update.tk/login.aspx?ref=invoice-Q4"]
    senderDomain:   ["example-supplier.com", "industry-news.io",
                      "billing-secure-update.tk", "hr-internal.corp.example"]
    act:          ["delivered", "delivered", "quarantined", "delivered"]
    threatCategory: ["clean", "clean", "phishing", "clean"]
    threatScore:    ["10", "20", "85", "5", "15"]
    cefSeverity:        ["informational", "high"]
    fname:       []
    attachmentCount: ["0", "1"]
```

**Field semantics:**
- `sender_email` / `sender_domain` — the malicious entry is the typo-squat `.tk` domain pretending to be a billing portal
- `url` — the credential-harvest landing page; this exact URL must reappear in Stage 2's proxy log so the SIEM correlates "the user who got the phish clicked it"
- `threat_category` / `threat_score` — most email gateways enrich with category + numeric risk score; `85` is in the "phishing" band
- `action: delivered` — the phish gets through to the user's inbox (the noise events also include some quarantines so the gateway doesn't look broken)
- `attachment_count: 0` — this is a credential-harvest phish (link, no attachment); a separate scenario covers macro-attachment phishing

**Why this fires Rule #9:** the email gateway entry combining `threat_category=phishing`, `threat_score>80`, `action=delivered`, and a known-bad sender domain matches the SIEM's "Phishing email with malicious link delivered" rule.

---

### Stage 2 — User clicks the link (proxy logs the GET) — 8 events over 90 seconds

Three minutes after delivery, `m.patel` opens the email and clicks. The proxy logs the HTTP GET. The credential harvester also serves a small JS bundle and posts the captured creds back, so we get 8 events total (1 GET to the login page + ~5 asset loads + 1 POST of credentials + 1 redirect).

**Data class:** `proxy`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[proxy].vendor>
  product: <stack[proxy].product>
  count:    8
  interval: 11
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["10.10.20.42"]
    shost:      ["wks-mpatel-01"]
    user:          ["m.patel"]
    spt:      ["49152", "51234", "57890", "60123"]
    dpt:      ["443"]
    proto:      ["6"]
    requestClientApplication:    ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0"]
    request:           ["https://billing-secure-update.tk/login.aspx?ref=invoice-Q4",
                    "https://billing-secure-update.tk/static/login.js",
                    "https://billing-secure-update.tk/static/style.css",
                    "https://billing-secure-update.tk/api/auth"]
    requestMethod:        ["GET", "GET", "POST"]
    httpStatusCode:   ["200", "302"]
    out:    ["840", "1420", "320"]
    in: ["18420", "4280", "212"]
    contentType:   ["text/html", "application/javascript", "text/css", "application/json"]
    act:        ["allow"]
    cat:      ["newly-registered-domain", "uncategorized"]
    threatCategory: ["suspicious", "phishing"]
    threatScore:    ["75", "82"]
    referer:        ["", "https://outlook.office.com/owa/"]
```

**Field semantics:**
- `src_ip` / `src_host` / `user` — bound to `m.patel`'s workstation; the user attribution lets the SIEM later say "the same user whose email got delivered the phish then clicked it"
- `url` — must include the EXACT URL from Stage 1's email so the SIEM correlates inbox→browser
- `method: POST` to `/api/auth` is the credential exfiltration — the proxy doesn't see the body but DOES see that the user just submitted form data to a new domain
- `category: newly-registered-domain` — the proxy enriches with domain age; phishing infrastructure is typically <30 days old
- `threat_category` / `threat_score` — proxy's URL-filtering verdict; `phishing/82` would normally block, but the proxy might be in monitor-mode for this category
- `referrer: https://outlook.office.com/owa/` on the redirect — proves the user came from webmail, sealing the inbox→click correlation

**Why this fires Rule #8:** the URL category (`phishing` or `newly-registered-domain`) combined with a POST containing form data crosses the "user accessed credential-harvest URL" threshold. Some SIEMs key on the URL category alone; others want the POST + reduce-confidence-on-GET pattern.

---

### Stage 3 — Stolen creds replayed at SaaS sign-in (impossible travel) — 1 event

Eight minutes after the click, the attacker replays the stolen creds against the SaaS provider (M365 or equivalent). The user has been signing in from `GB` for months; this attempt is from `RU`. MFA isn't triggered because the attacker uses an OAuth client that the user authorized in Stage 4 — but at THIS point, just a regular sign-in.

**Data class:** `saas`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[saas].vendor>
  product: <stack[saas].product>
  count:    1
  interval: 1
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    user:                  ["m.patel@corp.example"]
    src:                ["91.243.59.108"]
    country:               ["RU"]
    act:                ["login_success"]
    authenticationResult: ["success"]
    authenticationMethod: ["password"]
    externalId:            ["SaaS-SESS-d92f3e1c-44a7-4b19-8c2e-f3a91d8e7c45"]
    requestClientApplication:            ["Mozilla/5.0 (X11; Linux x86_64) Firefox/115.0"]
    deviceId:             ["unknown"]
    cefSeverity:              ["informational"]
```

**Field semantics:**
- `country: RU` vs the user's normal `GB` — the geographic delta is what fires impossible travel
- `mfa_required: false` — many tenants only enforce MFA for risky sign-ins; a "normal-looking" password sign-in skips MFA, which is exactly the bypass attackers exploit
- `device_id: unknown` + `device_compliance: non-compliant` — the attacker's machine isn't in the tenant's intune/MDM enrollment
- `session_id` — propagate this value into Stages 4-5 so all post-auth actions correlate

**Baseline pre-seed (skip if tenant has >2 weeks of real sign-in history):**

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[saas].vendor>
  product: <stack[saas].product>
  count:    1
  interval: 7200
  max_events: 20
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    user:    ["m.patel@corp.example"]
    src:  ["86.150.42.18", "86.150.42.91", "10.10.20.42"]
    country: ["GB"]
    act:  ["login_success"]
```

**Why this fires Rule #4:** geographic distance from the user's last successful sign-in (`GB`) to this one (`RU`) within hours is the impossible-travel signal. Some SIEMs also factor in IP reputation (`91.243.59.108` is in known-bad ranges) for higher-confidence alerts.

---

### Stage 4 — OAuth consent grant to malicious app — 3 events over 90 seconds

The attacker, now signed in as `m.patel`, navigates the OAuth consent flow to grant a malicious app the `Mail.ReadWrite`, `Mail.Send`, `Files.ReadWrite.All` permissions. The user already authenticated; the consent grant is a separate audit event.

**Data class:** `saas`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[saas].vendor>
  product: <stack[saas].product>
  count:    1
  interval: 30
  max_events: 3
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    user:                  ["m.patel@corp.example"]
    act:                ["consent_to_application", "add_oauth2permissiongrant",
                            "add_app_role_assignment"]
    operation:             ["Add app role assignment grant to user",
                            "Add delegated permission grant",
                            "Consent to application"]
    scope:                 ["User.Read", "offline_access"]
    externalId:            ["SaaS-SESS-d92f3e1c-44a7-4b19-8c2e-f3a91d8e7c45"]
    src:                ["91.243.59.108"]
    cefSeverity:              ["high"]
```

**Field semantics:**
- `app_publisher: unverified` — Microsoft Graph specifically flags apps without verified publisher; this is the field most consent-abuse rules key on
- `permissions_granted` — the high-risk permission set (read+write+send mail, all files) is the strongest single signal
- `consent_type: UserConsent` — the user consented (vs admin consent); user-consented apps are exactly the abuse vector because tenants often allow user consent without review
- `target_resource: 00000003-...` — Microsoft Graph's resource ID; populating it makes the recipe land in the correct M365 audit field

**Why this fires Rule #10:** the combination `app_publisher=unverified` + high-risk permissions (`Mail.ReadWrite` + `Files.ReadWrite.All`) + `consent_type=UserConsent` is the textbook OAuth abuse signature.

---

### Stage 5 — Inbox rule + bulk download (persistence + exfiltration) — ~125 events over 8 minutes

With the OAuth grant, the attacker (a) creates an inbox forwarding rule so future emails to `m.patel` flow to their mailbox, and (b) bulk-downloads the user's OneDrive `Q4-Claims-Documents` folder.

**Sub-stage 5A — inbox forwarding rule** (1 event)

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[saas].vendor>
  product: <stack[saas].product>
  count:    1
  interval: 1
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    user:           ["m.patel@corp.example"]
    act:         ["new-inboxrule"]
    operation:      ["New-InboxRule"]
    ruleName:      ["Auto-Archive External"]
    ruleAction:    ["ForwardTo"]
    externalId:     ["SaaS-SESS-d92f3e1c-44a7-4b19-8c2e-f3a91d8e7c45"]
    src:         ["91.243.59.108"]
    cefSeverity:       ["high"]
```

**Sub-stage 5B — bulk OneDrive download** (~120 events over 7 min)

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[saas].vendor>
  product: <stack[saas].product>
  count:    1
  interval: 4
  max_events: 120
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    user:        ["m.patel@corp.example"]
    act:      ["FileDownloaded"]
    operation:   ["FileDownloaded"]
    fname:   ["claim-INV-2891-Q4.pdf", "policy-renewal-2891.docx",
                  "customer-data-export.xlsx", "claims-summary-Q4.pdf"]
    request:    ["/personal/m_patel_acme_example/Documents/Q4-Claims-Documents"]
    out:       ["245000", "180000", "5240000", "320000", "890000"]
    src:   ["91.243.59.108"]
    externalId:  ["SaaS-SESS-d92f3e1c-44a7-4b19-8c2e-f3a91d8e7c45"]
    country:     ["RU"]
    cefSeverity:    ["medium"]
```

**Sub-stage 5C — egress to personal cloud (proxy or firewall)**

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[proxy].vendor>
  product: <stack[proxy].product>
  count:    1
  interval: 24
  max_events: 20
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["10.10.20.42"]
    user:          ["m.patel"]
    request:           ["https://www.dropbox.com/upload",
                    "https://api.dropboxapi.com/2/files/upload"]
    requestMethod:        ["POST"]
    httpStatusCode:   ["200"]
    out:    ["5242880", "10485760", "8388608"]
    contentType:  ["application/octet-stream"]
    act:        ["allow"]
    cat:      ["file-sharing", "personal-cloud-storage"]
    threatScore:  ["35"]
```

**Why this fires Rules #11 and #20:**
- **#11 (Mailbox Forwarding Rule Abuse):** `forward_external=true` to a non-corporate domain (`protonmail.com`) created from a non-compliant device + during an anomalous session = textbook signature
- **#20 (Data Exfiltration to Personal Cloud Storage):** large bulk transfer (`bytes` totals to ~200 MB across 120 file downloads) within minutes, then proxy POST to `dropbox.com` with multi-MB payloads — both signals together are unambiguous

---

### Stage 6 — Cloud IAM service-account key creation (SaaS-to-IaaS pivot) — 5 events over 4 minutes

Eight minutes after Stage 5, the attacker uses the still-live OAuth-token session to hop from SaaS into
the cloud platform's web console (Workspace/M365 SSO reaches GCP Console the same way it reaches any
federated app). Once in the cloud project, they create a new service account with broad permissions,
then mint a JSON key for it — a long-lived credential that survives `m.patel` resetting their password,
since it was never tied to the password in the first place.

**Data class:** `cloud`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[cloud].vendor>
  product: <stack[cloud].product>
  count:    5
  interval: 48
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:      ["91.243.59.108"]
    country:       ["RU"]
    act:        ["google.iam.admin.v1.CreateServiceAccount",
                    "google.iam.admin.v1.CreateServiceAccountKey",
                    "google.iam.admin.v1.SetIamPolicy"]
    apiEndpoint:  ["iam.googleapis.com"]
    requestMethod:    ["projects.serviceAccounts.create",
                    "projects.serviceAccounts.keys.create",
                    "projects.setIamPolicy"]
    resourceName: ["projects/gcp-prod-ExampleCorp/serviceAccounts/data-export-svc@gcp-prod-ExampleCorp.iam.gserviceaccount.com",
                    "projects/gcp-prod-ExampleCorp/serviceAccounts/data-export-svc@gcp-prod-ExampleCorp.iam.gserviceaccount.com/keys/8f3a91d2c4b7e5a8d6f9b2c1e4a7d3f5b8c2e9a1"]
    accessLevel:  ["roles/owner",
                    "roles/iam.serviceAccountTokenCreator",
                    "roles/iam.serviceAccountUser"]
    email:      ["data-export-svc@gcp-prod-ExampleCorp.iam.gserviceaccount.com"]
    keyId:     ["8f3a91d2c4b7e5a8d6f9b2c1e4a7d3f5b8c2e9a1"]
    keyType:   ["USER_MANAGED"]
    authenticationMethod: ["oauth_token"]
    externalId:            ["SaaS-SESS-d92f3e1c-44a7-4b19-8c2e-f3a91d8e7c45"]
    cefSeverity:      ["critical"]
```

**Field semantics:**
- `externalId` — the SAME session ID propagated from Stages 3-5, so this stage pivots into one case with
  everything before it rather than reading as an unrelated event
- `src` / `country` — still the attacker's `91.243.59.108` / `RU`, not the legitimate user's IP; the
  cloud audit log records the actor as `m.patel@corp.example` (via `authenticationMethod: oauth_token`)
  but the network origin is the tell
- `act: CreateServiceAccount + CreateServiceAccountKey + SetIamPolicy` — the canonical "establish
  persistent backdoor access" sequence
- `email: data-export-svc@...` — the SA name is intentionally innocuous, sounds like a legitimate data
  pipeline component
- `keyType: USER_MANAGED` — the riskiest key type; a long-lived JSON file the attacker now controls
- `accessLevel: roles/owner` — the SA gets full project ownership, the maximal escalation

**Why this fires Rule #17:** an IAM-key-creation event with role escalation to `roles/owner` from an
anomalous actor IP is high-severity in any modern cloud-detection ruleset. Even ignoring the IP, the
SA-with-Owner-and-self-impersonation pattern is suspicious enough to fire on its own.

---

## Verification

| Indicator | Where to check |
|---|---|
| Phishing email rule fired with `m.patel` recipient | XSIAM Issues, last 30 min |
| Proxy/URL alert for `billing-secure-update.tk` | XSIAM Issues |
| Impossible travel for `m.patel` (`GB` → `RU`) | XSIAM Issues |
| OAuth consent abuse alert with `app_id=8ba2f3d4-...` | XSIAM Issues |
| Mailbox rule abuse with `forward_to=*@protonmail.com` | XSIAM Issues |
| Exfiltration alert tied to OneDrive bulk-download volume | XSIAM Issues |
| Cloud IAM SA key creation with `roles/owner` | XSIAM Issues |
| Pivotable: filter `user=m.patel`, see all 7 alerts in one timeline | XQL: `config timeframe = 24h \| dataset = msft_o365_audit_raw \| filter UserId = "m.patel@corp.example" \| limit 20` |

## Tear-down

```yaml
xlog.list_workers:
xlog.kill_worker:
  worker_id: <each>
```

## Adapting per deployment

Replace `m.patel@corp.example` with the operator's chosen test user. The Stages 1-5 attack pattern is
identity-agnostic; the OAuth consent + forwarding rule + bulk download chain is identical regardless of
which user is targeted. Stage 6 (cloud pivot) is the exception: it's most realistic against a user who
genuinely has cloud platform admin in the tenant, so the escalation matches their actual IAM
hierarchy — pick accordingly, or skip Stage 6 if no target user with cloud access fits the exercise.
