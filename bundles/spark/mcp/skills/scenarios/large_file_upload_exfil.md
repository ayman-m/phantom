---
name: large_file_upload_exfil
displayName: Large file upload exfil
category: scenarios
description: 'Three-pattern data-exfiltration skill covering large-file upload AND insider-threat SaaS bulk-download patterns. Stage 1: workstation outbound bulk upload to file-sharing service via HTTPS (proxy-visible) — the routine end-user/compromised-endpoint case. Stage 2: server outbound bulk upload (anomalous direction — web servers should rarely initiate outbound), chaining from web_app_to_webshell_to_exfil. Stage 3: a privileged user (or compromised account) bulk-downloads from corporate SaaS then re-uploads to personal cloud (M365 + proxy chain) — the leaving-employee / insider-threat pattern, with realistic baseline-deviation reasoning (a user''s history, not authentication anomalies, is the signal). Each stage emits high-volume bytes_sent / bytes_received imbalance + multi-MB content_length + file-sharing-category destination. Vendor-agnostic — agent resolves vendor/product from the operator''s installed data sources at runtime. Triggers 3 XSIAM rules: Data Exfiltration to Personal Cloud Storage (#20), Anomalous Outbound Volume from Server, Mailbox / SaaS data access anomaly (#11, bulk download outside baseline).'
icon: upload_file
source: platform
loadingMode: on-demand
locked: false
attack:
  - 'TA0009: Collection (T1213.002 SharePoint, T1213.001 Confluence)'
  - 'TA0010: Exfiltration (T1567.002 Exfiltration to Cloud Storage, T1041 Exfiltration Over C2 Channel, T1048.003 Exfiltration Over Unencrypted Non-C2 Protocol)'
---

# Skill: Large file upload exfiltration

## Category

scenarios

## Attack Type

Data exfiltration via outbound HTTPS to file-sharing services or personal cloud storage. The single most common exfil channel in 2024-26 IR reports — replaced FTP/SFTP/S3-direct exfil because TLS hides the content from network inspection and file-sharing categories are typically allowed (operator policy: "Dropbox is fine for personal use during lunch").

Detection has to key on **volume + destination category + direction anomaly** rather than content. This skill validates each of those signals.

Three distinct patterns covered:

- **Workstation → file-sharing**: routine end-user case (insider threat, compromised endpoint)
- **Server → file-sharing**: anomalous direction (web/app servers should rarely initiate outbound to non-CDN destinations)
- **SaaS-collected → personal cloud**: bulk download from corporate SaaS then re-upload to attacker-controlled storage

## MITRE ATT&CK Tactics

- TA0009: Collection (T1213.002 SharePoint, T1213.001 Confluence)
- TA0010: Exfiltration (T1567.002 Exfiltration to Cloud Storage, T1041 Exfiltration Over C2 Channel, T1048.003 Exfiltration Over Unencrypted Non-C2 Protocol)

## XSIAM analytics rules triggered

| # | Rule | Stage |
|---|---|---|
| 20 | Data Exfiltration to Personal Cloud Storage | Stages 1 + 2 + 3 |
| - | Anomalous Outbound Volume from Server | Stage 2 |
| 11 | Mailbox / SaaS data access anomaly (bulk download outside baseline) | Stage 3A |

## Data classes used

| Stage | Data class | If missing |
|---|---|---|
| 1, 2 | `proxy` | Required for URL category + outbound visibility |
| 1, 2 | `firewall` | Confirms volume at perimeter |
| 3 | `saas` | Required — SaaS audit log captures the bulk-download initiator |

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
3. For each stage whose class is `MISSING` (and has no substitute in the table), say this to the operator, with the class and stage filled in: "No installed data source covers the `<class>` class, so I am skipping Stage <N> (<stage name>). I will not generate it with a generic schema. Install a `<class>` data source from the Marketplace to include it." Then create NO worker for that stage: not with a generic schema, not with another class's schema, not with a guessed vendor/product. Continue with the stages whose classes are covered. If every stage is `MISSING`, stop after saying it.
   - Missing `saas`: skip Stage 3 entirely (3A and 3B). This is the case the sentence above is for: the SaaS bulk download is never generated from a generic schema, even if other stages ran.
   - Missing `proxy`: skip only the proxy sub-stages (1A, 2A, and the proxy half of 3B). The firewall sub-stages (1B, 2B, and the firewall half of 3B) still run if a `firewall` entry is installed.
   - Missing `firewall`: skip only the firewall sub-stages (1B, 2B, and the firewall half of 3B).
4. In your final report, list every stage you skipped or substituted and which of the alerts above will therefore not fire.

## Pre-flight: read the organization

Call `organization_get(section="personas")` once. It names the outlier (the person and workstation an inside attack runs from) and, for Stage 2, `organization_get(section="hosts", filter="role=dmz")` gives the public web server. Every identity below comes from there; do not invent a user, host or address.

## Narrative thread

- **Insider user (Stages 1 and 3):** the organization's outlier persona (`flag=outlier`), so the behaviour stands out against peers. Take the login, email, workstation and workstation address from the people row. Phantom Lab example: `aalzamil` (Anas Alzamil, DevOps Engineer, `anas.alzamil@phantom.lab`), workstation PHWS-036 at `10.20.16.55`. Gave 2-week notice 3 days before Stage 3: not a SIEM-visible fact, but the realistic context for why privileged bulk-download right before leaving reads as suspicious rather than routine.
- **Compromised web server (Stage 2):** the organization's public web host, PHDMZ-WEB01 (`organization_get section=hosts filter=role=dmz`; `172.16.10.10` on Phantom Lab). Keep its internal DMZ address in `src` (the "server initiates outbound" signal depends on it); its public egress address is `egress.dmz_public.PHDMZ-WEB01` (`151.254.90.10` on Phantom Lab) for any translated-source field.
- **Personal cloud destinations:** Dropbox (`162.125.x.x`), Google Drive personal (`172.217.x.x`), Mega.nz (`66.203.x.x`), WeTransfer (`paste.dropfiles.io`). These are external services, not part of the organization.
- **SaaS source (Stage 3):** OneDrive `personal/<insider email with "." and "@" replaced by "_">/Documents/Claims-Q4-Archive` (Phantom Lab example: `personal/anas_alzamil_phantom_lab/Documents/Claims-Q4-Archive`, ~600 docs, ~4 GB total)
- **Wall-clock time:** Stage 1 ~25 min sustained upload. Stage 2 ~10 min server-side burst (more aggressive). Stage 3 ~30 min SaaS bulk download + ~25 min re-upload (overlapping). Stages 1+2 can run in parallel; Stage 3 has internal sequencing (download → upload).

If the organization has no outlier persona or no public web host, tell the operator and offer `organization_update` instead of inventing one.

---

### Stage 1 — Workstation outbound bulk upload to file-sharing — ~250 events over 25 minutes

The user (insider OR compromised endpoint via attacker tooling) systematically uploads chunks to their personal Dropbox account. The proxy logs each upload as a multi-MB POST/PUT.

**Sub-stage 1A — proxy outbound**

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[proxy].vendor>
  product: <stack[proxy].product>
  count:    250
  interval: 6
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["<insider workstation address: 10.20.16.55>"]
    shost:      ["<insider workstation: PHWS-036>"]
    suser:          ["<insider login: aalzamil>"]
    spt:      ["49152", "51234", "57890", "60123"]
    dpt:      ["443"]
    proto:      ["6"]
    request:           ["https://www.dropbox.com/upload",
                    "https://content.dropboxapi.com/2/files/upload",
                    "https://content.dropboxapi.com/2/files/upload_session/append_v2",
                    "https://content.dropboxapi.com/2/files/upload_session/finish",
                    "https://drive.google.com/u/1/uc?id=upload",
                    "https://www.mega.nz/upload"]
    requestMethod:        ["POST", "PUT"]
    httpStatusCode:   ["200", "201"]
    requestClientApplication:    ["Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "DropboxClient/202",
                    "Dropbox/2024.06"]
    act:        ["allow"]
    out:    ["10485760", "20971520", "5242880",
                    "12582912", "8388608", "16777216",
                    "26214400"]
    in: ["240", "180", "320", "412"]
    contentType:  ["application/octet-stream", "application/zip"]
    contentLength: ["10485760", "20971520", "5242880"]
    cat:      ["file-sharing", "personal-cloud-storage"]
    threatScore:  ["55", "65"]
    dhost:        ["dropbox.com", "dropboxapi.com",
                    "drive.google.com", "mega.nz"]
```

**Sub-stage 1B — firewall confirmation**

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[firewall].vendor>
  product: <stack[firewall].product>
  count:    1
  interval: 15
  max_events: 100
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["<insider workstation address: 10.20.16.55>"]
    dst:        ["162.125.4.20", "162.125.5.20", "104.21.x.x",
                    "172.217.x.x", "66.203.x.x"]
    spt:      ["49152", "51234", "57890", "60123"]
    dpt:      ["443"]
    proto:      ["6"]
    act:        ["allow"]
    app:           ["ssl", "dropbox", "google-base", "mega"]
    out:    ["10485760", "20971520", "5242880",
                    "12582912", "8388608"]
    in: ["240", "180", "320"]
    country:       ["US"]
    threatCategory: ["file-sharing"]
    sessionDuration: ["18", "25", "12", "32"]
```

**Field semantics:**
- `bytes_sent` — multi-MB per session (5-26 MB range), 250 events × ~12 MB avg = ~3 GB total uploaded
- `bytes_received` — tiny (just acknowledgments) — the imbalance is the strongest signal
- `category: file-sharing / personal-cloud-storage` — proxy classification
- `domain_age_days: 10000` — destinations are decades-old (Dropbox is real); the signal is NOT destination age, it's category + volume + direction

**Why this fires Rule #20:** classic exfil — high outbound volume from a workstation to a category that's typically allowed (file-sharing). Threshold: ≥1 GB outbound to file-sharing in <1 hour from one source. 3 GB / 25 min crosses it 7x over.

---

### Stage 2 — Server outbound bulk upload (anomalous direction) — ~100 events over 10 minutes

After web-app compromise of PHDMZ-WEB01 (per `web_app_to_webshell_to_exfil`), the attacker uses the web shell to package DB content + source code, then exfiltrates it via outbound HTTPS to a file-sharing service. **This is the anomalous-direction signal: web servers should rarely initiate outbound to non-CDN destinations.**

**Sub-stage 2A — proxy**

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[proxy].vendor>
  product: <stack[proxy].product>
  count:    60
  interval: 10
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["<web server address: 172.16.10.10 for PHDMZ-WEB01>"]
    shost:      ["<web server: PHDMZ-WEB01>"]
    spt:      ["41024", "41128", "41234", "41512"]
    dpt:      ["443"]
    proto:      ["6"]
    request:           ["https://paste.dropfiles.io/upload",
                    "https://api.dropfiles.io/v2/objects",
                    "https://transfer.sh/?action=upload",
                    "https://0x0.st/"]
    requestMethod:        ["POST", "PUT"]
    httpStatusCode:   ["200", "201"]
    requestClientApplication:    ["curl/7.81.0", "Wget/1.21.3", "python-requests/2.31.0"]
    act:        ["allow"]
    out:    ["10485760", "20971520", "5242880",
                    "8388608", "16777216", "33554432"]
    in: ["240", "180", "320"]
    contentType:  ["application/octet-stream", "application/zip"]
    contentLength: ["10485760", "20971520", "33554432"]
    cat:      ["file-sharing", "personal-cloud-storage", "uncategorized"]
    threatScore:  ["55", "70"]
    dhost:        ["paste.dropfiles.io", "transfer.sh", "0x0.st"]
```

**Sub-stage 2B — firewall**

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[firewall].vendor>
  product: <stack[firewall].product>
  count:    1
  interval: 15
  max_events: 40
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["<web server address: 172.16.10.10 for PHDMZ-WEB01>"]
    dst:        ["104.21.x.x", "172.67.x.x", "66.203.x.x"]
    spt:      ["41024", "41128", "41234", "41512"]
    dpt:      ["443"]
    proto:      ["6"]
    act:        ["allow"]
    app:           ["ssl"]
    out:    ["10485760", "20971520", "33554432"]
    in: ["240", "180"]
    country:       ["US"]
    threatCategory: ["file-sharing"]
```

**Field semantics:**
- `src_ip` (the web server's DMZ address, `172.16.10.10` for PHDMZ-WEB01) — the WEB SERVER initiates outbound, not a user workstation. **This is the strongest single signal.** Web servers should accept inbound connections; outbound to non-CDN destinations is suspicious by direction alone
- `bytes_sent` — chunks up to 33 MB per session (server can stage larger archives than a workstation)
- `domain_age_days: 1-12` — destinations are NEW (newly-stood-up attacker infrastructure for this campaign), unlike Stage 1's mature Dropbox

**Why this fires the "Anomalous Outbound Volume from Server" rule:** server-class assets have egress baselines (mostly to CDNs, package mirrors, NTP servers). Multi-MB POST traffic to file-sharing categories from a web tier is an unmistakable deviation.

---

### Stage 3 — SaaS bulk-download → personal cloud upload — ~800 events over 30 minutes

The privileged user (or compromised account) bulk-downloads from corporate OneDrive, then re-uploads to personal cloud. Two-phase: collection (Stage 3A — SaaS-side) followed by exfiltration (Stage 3B — proxy + firewall).

**Sub-stage 3A — SaaS bulk download (Collection)**

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[saas].vendor>
  product: <stack[saas].product>
  count:    600
  interval: 3
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    suser:        ["<insider email: anas.alzamil@phantom.lab>"]
    src:      ["<insider workstation address: 10.20.16.55>"]
    act:      ["FileDownloaded", "FileSyncDownloadedFull",
                  "FilePreviewed", "FileAccessed",
                  "PageViewed", "FolderListed"]
    operation:   ["FileDownloaded", "FileSyncDownloadedFull"]
    fname:   ["claims-batch-Q4-001.xlsx",
                  "clinical-trial-EU-results.pdf",
                  "patient-data-export-aug-2024.csv",
                  "research-archive-2023.zip",
                  "policy-renewals-Q4.xlsx",
                  "actuarial-models-v3.zip"]
    request:    ["/personal/<insider email with . and @ as _>/Documents/Claims-Q4-Archive",
                  "/sites/claims-data-2024",
                  "/sites/clinical-research-eu"]
    out:       ["180000", "245000", "890000", "5240000",
                  "12480000", "48800000", "4280000"]
    client_app:   ["OneDrive Sync Engine",
                  "OneDrive for Business"]
    country:     ["<the insider's normal country: SA>"]
    cefSeverity:    ["informational", "medium"]
    fileType:   ["xlsx", "pdf", "csv", "zip"]
    sensitivity_label:   ["Confidential", "Restricted", "PHI"]
```

**Sub-stage 3B — proxy + firewall re-upload to personal cloud**

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[proxy].vendor>
  product: <stack[proxy].product>
  count:    200
  interval: 9
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["<insider workstation address: 10.20.16.55>"]
    shost:      ["<insider workstation: PHWS-036>"]
    suser:          ["<insider login: aalzamil>"]
    spt:      ["49251", "51380", "57902", "60127"]
    dpt:      ["443"]
    proto:      ["6"]
    request:           ["https://www.dropbox.com/upload",
                    "https://content.dropboxapi.com/2/files/upload",
                    "https://drive.google.com/u/1/uc?id=upload"]
    requestMethod:        ["POST", "PUT"]
    httpStatusCode:   ["200", "201"]
    requestClientApplication:    ["Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "DropboxClient/202"]
    act:        ["allow"]
    out:    ["20971520", "33554432", "10485760", "16777216"]
    in: ["240", "180", "320"]
    contentType:  ["application/octet-stream", "application/zip"]
    contentLength: ["20971520", "33554432"]
    cat:      ["file-sharing", "personal-cloud-storage"]
    threatScore:  ["55", "65"]
    dhost:        ["dropbox.com", "dropboxapi.com", "drive.google.com"]
```

**Field semantics:**
- `suser` — the same legitimate user across all 600 download events; the anomaly is volume relative to THIS user's own baseline, not an authentication anomaly. A typical privileged user's baseline is ~5 MB/day; 4 GB in 30 minutes is several orders of magnitude beyond it
- `action: FileDownloaded` for 600 events in Stage 3A — by itself crosses any "bulk SaaS download" threshold (typical: ≥100 downloads / 30 min)
- `country` stays constant (not impossible-travel) — the user is signed in from where they normally are; the signal is volume, not geo
- The TIMING correlation is what makes Stage 3 high-fidelity: bulk SaaS download AND outbound personal-cloud upload from same user within minutes = high-confidence exfil
- `sensitivity_label` — MIP / DLP-classified content; "Confidential", "PHI", "Restricted" enrich the alert severity at the SIEM

**Why this fires Rule #11 (Stage 3A alone) and Rule #20 (Stage 3A+3B combined):**
- Rule #11 fires on Stage 3A by itself: modern SaaS-detection rules key on "user X downloaded N times more than their 30-day baseline in a Y-hour window" — 600 file events in 30 min is unmistakable even before any upload happens
- Rule #20 needs the combination: SaaS downloads alone don't fire it, and personal-cloud uploads alone don't either (users genuinely use Dropbox sometimes) — what fires it is the TEMPORAL CORRELATION of both from the same user, totaling multi-GB
- 600 file-download events / 30 min from one user crosses the bulk-download threshold (typical: ≥100 / 30 min), followed by ~200 outbound POST events from the same user to file-sharing destinations within the same window

---

## Verification

| Indicator | Where to check |
|---|---|
| Stage 1 exfil-to-file-sharing alert (workstation → Dropbox volume) | XSIAM Issues |
| Stage 2 server-outbound-anomaly alert (PHDMZ-WEB01 → uncategorized destinations) | XSIAM Issues |
| Stage 3A bulk-SaaS-download alert (the insider's 600 downloads / 30 min) | XSIAM Issues |
| Stage 3B exfil-to-file-sharing alert (re-upload following Stage 3A) | XSIAM Issues |
| Pivotable: filter `user=<insider login>`, see all 4 stages on one timeline | XQL: `config timeframe = 24h \| dataset = <dataset_name of the saas entry> \| filter <its user field> = "<insider email>" \| limit 20` |

## Tear-down

```yaml
xlog.list_workers:
xlog.kill_worker:
  worker_id: <each>
```

## Adapting per deployment

The illustrative volumes (3 GB workstation upload, 4 GB SaaS download) are calibrated to cleanly cross common SIEM thresholds. For a customer's environment with HIGHER-volume baselines (e.g. media production company where multi-GB uploads are routine), bump the volumes 5-10× to ensure the signal stands out from baseline traffic. For lower-volume environments (small-business SaaS tenants), the default volumes are adequate.

**Stage 3A (Rule #11) needs a baseline to deviate from.** That rule fires on deviation from the
user's own history — on a fresh tenant with no prior `FileDownloaded` activity for the chosen
user, a sudden burst doesn't read as anomalous because there's no baseline to compare against.
Pre-seed ~30 days of low-volume download events for the user (a handful of files/day) before
running Stage 3, or use `baseline_normal_activity` to establish it generically first.
