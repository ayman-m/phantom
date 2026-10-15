---
name: bootstrap_dataset_fields
displayName: Bootstrap dataset fields
category: foundation
description: 'Generates ~100 sample events per data source installed in the operator''s Marketplace, each populated with the maximum set of fields characteristic of that data source class. Solves the XSIAM "I can''t model what doesn''t exist" problem — Cortex XSIAM cannot create a dataset or field-mapping for telemetry it has never received. This skill seeds each dataset with field-rich sample data so field-mapping work can begin. Vendor-agnostic — agent reads the operator''s installed data sources at runtime and uses whichever firewall, EDR, NDR, etc. products are configured. Run once per deployment after installing data sources; re-run when adding a new data source.'
icon: dataset_linked
source: platform
loadingMode: on-demand
locked: false
attack: []
---

# Skill: Bootstrap dataset fields

## Category

foundation

## Purpose

Solves the XSIAM (and any modern SIEM's) chicken-and-egg problem: **you cannot model or field-map a dataset that has never received data.** Configuring an XSIAM ingestion broker for `vendor_proofpoint_tap_raw` and immediately opening the field-mapping UI shows nothing — XSIAM hasn't seen any rows yet. The platform won't let you write a parser for telemetry it has never seen.

This skill seeds each dataset for the operator's installed data sources with ~100 events containing the maximum relevant set of fields from xlog's catalog. After running, every dataset in XSIAM has populated rows with realistic field shapes, and field-mapping work can proceed.

**When to run:**
- Once per deployment, immediately after installing data sources at `/connectors`
- After installing a new data source (only the new source's worker runs)
- When a vendor's expected field set has expanded (operator can edit the field templates below and re-run)

**This is a bootstrap utility, not detection content.** The events generated have realistic field shapes but no narrative — they're designed to populate dataset schemas, not to fire any specific analytics rule.

## MITRE ATT&CK Tactics

Not applicable — bootstrap utility, not an attack-simulation or detection-validation skill.

## Pre-flight

Before generating any data, call `data_sources_installed_as_vendors` once. If `vendors[]` is empty, stop and tell the operator: no data sources are installed — install at least one from the Marketplace before this skill can run. Otherwise iterate every entry in `vendors[]`. For each entry, look up the field template by `data_source_class` from the per-class sections below. If a class isn't covered (operator has an installed data source outside the templates below), fall back to a minimal-fields recipe and surface a warning to the operator at the end.

Resolve the destination as a store reference: call `log_destinations_list` once and pass `destination: "logdest:<id>"`. Never pass a destination's `type` (`syslog`) — that is not an accepted value.

Each worker uses `count: 100`, `interval: 1`. These recipes pass **no** `schema_override`, so they run on the sender where `count` is a **total**: each worker delivers exactly 100 events and then stops on its own, which is why the verification step below expects every worker to reach `Stopped`. One event per second per source, 100 seconds, all sources in parallel.

Do not set `interval` below 1 — it is an integer, so `0.1` silently became `0`, meaning no throttle at all, and is now rejected outright. Do not raise `count` to go faster either: the server caps total generation rate across all live workers, and 100 events per source is enough to populate a dataset schema.

### Pre-flight: read the organization

Every user, host and address in the recipes below must belong to the active organization, so the seeded rows already look like the company the rest of the platform simulates. Call `organization_get(section="overview")` once, then `organization_get(section="people", limit=5)` and `organization_get(section="hosts", filter="role=server")`. Take one ordinary person (login, email, workstation name and address, `home_ip`), because lists of several people would be sampled independently and pair a login with another person's workstation, a domain controller, the file, application and SQL servers, and the DMZ hosts (`filter=role=dmz`). The values written in the recipes are the Phantom Lab ones, labelled as examples; swap them for the active organization's own. Never use the leaver (Phantom Lab: `ralsayegh`) or the break-glass account. Attacker-side addresses (`192.0.2.42`, `203.0.113.18`) and external sample domains stay as written, because they are not part of the organization. If a recipe needs an entity the organization lacks, tell the operator and offer `organization_update` instead of inventing one.

**Use parallel `xlog.create_data_worker` calls (one per installed data source), NOT a single scenario.** The scenarios tool exists for narrative kill-chains. This skill is independent per-source bootstrap; parallel workers give per-source independence (one worker failing doesn't block others) and per-source observability via `xlog.list_workers`.

## Field templates per data source class

Each per-class section below has the **field set the skill applies for that class** plus a complete `xlog.create_data_worker` recipe template. The agent picks the template matching `<stack[<entry>].data_source_class>` for each stack entry, then substitutes vendor/product placeholders at runtime.

**These field lists are starting points, not hard rules.** Operators can edit any class's field set via `/skills` → Save (the skill MD lives at `/app/skills/foundation/bootstrap_dataset_fields.md`); the agent picks up the change on next invocation.

---

### Firewall

5-tuple flow logging + action verdict + app classification + volume + geo + threat enrichment. ~22 fields. Most common SIEM ingest source by volume.

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[<entry>].vendor>
  product: <stack[<entry>].product>
  count:    100
  interval: 1
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["192.0.2.42", "192.0.2.91", "203.0.113.18", "198.51.100.42"]
    dst:        ["172.16.10.10", "172.16.10.12", "10.20.16.20", "10.20.1.20"]   # Phantom Lab: PHDMZ-WEB01, PHDMZ-VPN01, PHWS-001, PHSRV-FS01
    spt:      ["49152", "51234", "57890", "60123"]
    dpt:      ["443", "80", "22", "3389", "445", "53"]
    proto:      ["tcp", "udp"]
    act:        ["allow", "deny", "drop"]
    actionStatus: ["success", "blocked"]
    app:           ["ssl", "ssh", "http", "dns", "smb"]
    out:    ["480", "640", "1024", "8192", "180"]
    in: ["240", "1280", "4096", "12480", "180"]
    packets:       ["3", "12", "48", "92"]
    country:       ["US", "GB", "DE", "JP", "BR", "RU"]
    asnSource:    ["AS15169", "AS8075", "AS13335"]
    asnDestination: ["AS15169", "AS8075", "AS13335"]
    threatCategory: ["clean", "suspicious", "malicious"]
    threatScore:  ["10", "35", "65", "82"]
    tcpFlags:     ["SYN", "SYN-ACK", "ACK", "FIN"]
    externalId:    ["sess-001", "sess-002", "sess-003"]
    sessionDuration: ["12", "45", "120", "240"]
```

---

### EDR (Endpoint Detection & Response)

Process tree + file activity + network-from-endpoint + user attribution + alert classification + MITRE mapping. ~20 fields. Highest-fidelity-per-event source typically.

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[<entry>].vendor>
  product: <stack[<entry>].product>
  count:    100
  interval: 1
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    shost:       ["PHWS-001"]      # ONE Phantom Lab person: login, workstation and address together
    src:         ["10.20.16.20"]
    suser:           ["nalharbi"]
    sproc:   ["powershell.exe", "cmd.exe", "explorer.exe", "WINWORD.EXE", "rundll32.exe"]
    parentProcessName: ["explorer.exe", "WINWORD.EXE", "powershell.exe", "cmd.exe"]
    spid:     ["1234", "5678", "9012"]
    commandLine:   ["powershell.exe -nop -w hidden", "cmd.exe /c whoami", "WINWORD.EXE /n test.docx"]
    filePath:      ["C:\\Users\\nalharbi\\Documents", "C:\\Windows\\Temp", "C:\\Program Files"]
    fname:      ["test.docx", "report.pdf", "tools.exe"]
    fileHash: ["b42c1f9e3a0d7c8b5e2f4a6d8e1b3c5a7f9d2e4b6c8a0d2f4e6c8a0b2d4f6c8e"]
    targetProcessName: ["lsass.exe", "explorer.exe"]
    targetPid:     ["604", "1234"]
    act:         ["process_create", "file_create", "registry_modify", "network_connection"]
    alertId:       ["alert-001", "alert-002", "alert-003"]
    alertName:     ["Suspicious PowerShell", "LSASS Memory Access", "Network Connection"]
    attackType:    ["powershell_encoded", "credential_dump", "lateral_movement"]
    attackSeverity: ["informational", "medium", "high", "critical"]
    mitreTechnique: ["T1059.001", "T1003.001", "T1021.002"]
    cefSeverity:       ["informational", "medium", "high", "critical"]
```

---

### NDR (Network Detection & Response)

East-west focus, anomaly-driven, baseline-deviation alerts. ~18 fields. Distinct from firewall (which is north-south + 5-tuple-only); NDR enriches with anomaly scoring + alert classification.

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[<entry>].vendor>
  product: <stack[<entry>].product>
  count:    100
  interval: 1
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["10.20.16.20"]       # one workstation (PHWS-001) and one server (PHSRV-FS01), each name with its own address
    shost:      ["PHWS-001"]
    dst:        ["10.20.1.20"]
    dhost:      ["PHSRV-FS01"]
    dpt:      ["445", "139", "3389", "5985", "1433"]
    proto:      ["6"]
    act:        ["alert", "monitor"]
    anomalyType:  ["lateral_movement", "first_time_admin_share", "unusual_internal_connection",
                    "wmi_rpc_anomaly", "smb_admin_share_pattern"]
    anomalyScore: ["72", "85", "91", "68"]
    alertName:    ["First-time admin$ share access", "WMI RPC anomaly", "Lateral RPC pattern"]
    alertType:    ["ndr_lateral_movement", "ndr_anomaly"]
    cefSeverity:      ["medium", "high", "critical"]
    attackCategory: ["lateral_movement", "reconnaissance"]
    attackType:   ["smb_admin_access", "rdp_lateral", "wmi_remote_exec"]
    out:    ["240", "1024", "4096", "8192"]
    in: ["180", "512", "2048", "8192"]
    suser:  ["nalharbi"]
    externalId:    ["sess-A1", "sess-B2"]
    mitreTechnique: ["T1021.002", "T1047", "T1021.001"]
```

---

### Proxy

HTTP request/response + user attribution + URL category filtering. ~18 fields. Critical for outbound visibility (data exfil, malicious URL access).

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[<entry>].vendor>
  product: <stack[<entry>].product>
  count:    100
  interval: 1
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["10.20.16.20"]       # ONE person: login, workstation and address together
    shost:      ["PHWS-001"]
    suser:          ["nalharbi"]
    request:           ["https://www.example.com/", "https://api.example.com/v1/data",
                    "https://cdn.example.com/static/app.js",
                    "https://dropbox.com/upload"]
    requestMethod:        ["GET", "POST", "PUT"]
    httpStatusCode:   ["200", "302", "404", "403", "500"]
    requestClientApplication:    ["Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "curl/7.81.0", "python-requests/2.31.0"]
    referer:       ["https://www.example.com/", ""]
    contentType:  ["text/html", "application/json", "application/octet-stream"]
    out:    ["480", "640", "1024", "10485760"]
    in: ["240", "12480", "4096", "180"]
    act:        ["allow", "block", "alert"]
    cat:      ["business", "newly-registered-domain", "file-sharing", "scanner"]
    threatCategory: ["clean", "suspicious", "phishing", "c2"]
    threatScore:  ["10", "35", "65", "82"]
    dhost:        ["www.example.com", "api.example.com", "dropbox.com"]
    country:       ["US", "GB", "DE"]
```

---

### Email Gateway

Sender/recipient + email body + attachment metadata + threat enrichment + DKIM/SPF/DMARC. ~19 fields. The phishing detection foundation.

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[<entry>].vendor>
  product: <stack[<entry>].product>
  count:    100
  interval: 1
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    senderEmail:    ["partners@external-supplier.com",
                      "newsletter@industry-news.io",
                      "invoices@billing-secure-update.tk"]
    senderDomain:   ["external-supplier.com", "industry-news.io",
                      "billing-secure-update.tk"]
    recipientEmail: ["noura.alharbi@phantom.lab", "mona.alessa@phantom.lab"]
    recipientDomain: ["phantom.lab"]
    emailSubject:   ["Q4 Newsletter", "Payment terms",
                      "URGENT: Invoice action required"]
    emailBody:      ["[redacted body sample]"]
    attachmentCount: ["0", "1", "2"]
    attachmentName: ["invoice.docm", "report.pdf", ""]
    attachmentHash: ["b42c1f9e3a0d...", "8a64dc4b...", ""]
    attachmentSize: ["180000", "245000", "0"]
    attachmentType: ["docm", "pdf", "xlsx", ""]
    act:          ["delivered", "quarantined", "blocked"]
    threatCategory: ["clean", "phishing", "malware"]
    threatScore:    ["10", "65", "82"]
    dkimResult:     ["pass", "fail", "neutral"]
    spfResult:      ["pass", "softfail", "fail"]
    dmarcResult:    ["pass", "fail", "quarantine"]
    cefSeverity:        ["informational", "high"]
```

---

### DNS

Query + response + source attribution + domain enrichment + threat tagging. ~15 fields. Compact but high-volume; critical for tunneling/DGA detection.

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[<entry>].vendor>
  product: <stack[<entry>].product>
  count:    100
  interval: 1
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:       ["10.20.16.20"]       # ONE person: login, workstation and address together
    shost:     ["PHWS-001"]
    suser:         ["nalharbi"]
    spt:     ["49152", "51234", "57890"]
    dpt:     ["53"]
    proto:     ["udp", "tcp"]
    query:        ["www.example.com", "api.example.com", "cdn.example.com",
                   "xkqp93jr9d2.cdn-update-svc.tk"]
    queryType:   ["A", "AAAA", "TXT", "MX", "PTR"]
    queryName:   ["www.example.com", "api.example.com"]
    responseCode: ["NOERROR", "NXDOMAIN", "SERVFAIL"]
    responseIp:  ["93.184.216.34", "192.0.2.42", ""]
    responseData: ["v=spf1 include:_spf.example.com ~all", ""]
    ttl:          ["300", "60", "30", "3600"]
    act:       ["allow", "block"]
    dhost:       ["example.com", "cdn-update-svc.tk"]
    threatCategory: ["clean", "suspicious", "c2"]
```

---

### WAF (Web Application Firewall)

HTTP request inspection + attack classification + rule match + source attribution. ~18 fields. The OWASP Top 10 detection layer.

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[<entry>].vendor>
  product: <stack[<entry>].product>
  count:    100
  interval: 1
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["192.0.2.42", "203.0.113.18", "198.51.100.42"]
    dst:        ["172.16.10.10"]   # Phantom Lab: PHDMZ-WEB01
    spt:      ["49152", "51234", "57890", "60123"]
    dpt:      ["443", "80"]
    proto:      ["6"]
    request:           ["/", "/login.php", "/api/v1/users", "/search.php?id=1",
                    "/admin/", "/.env"]
    requestMethod:        ["GET", "POST"]
    httpStatusCode:   ["200", "403", "404", "500"]
    requestClientApplication:    ["Mozilla/5.0", "sqlmap/1.7.2", "curl/7.81.0"]
    act:        ["allow", "block", "alert"]
    attackType:   ["sql-injection", "xss", "directory-traversal",
                    "command-injection", "scanner-fingerprint"]
    attackSeverity: ["informational", "medium", "high", "critical"]
    attackCategory: ["sql-injection", "xss", "lfi", "rce"]
    ruleId:       ["942100", "942130", "941100", "930100", "920270"]
    ruleName:     ["SQL Injection: Common Testing", "XSS Attack Detected",
                    "Restricted File Access"]
    out:    ["480", "640", "1240"]
    in: ["240", "1280", "12480"]
    threatScore:  ["35", "65", "82", "95"]
    anomalyScore: ["45", "72", "88"]
    country:       ["US", "RU", "CN", "DE"]
```

---

### Load Balancer

HTTP traffic + backend pool routing + response timing. ~15 fields. Less commonly field-mapped into XSIAM (operators usually use firewall/WAF instead) but included here for stack completeness.

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[<entry>].vendor>
  product: <stack[<entry>].product>
  count:    100
  interval: 1
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["192.0.2.42", "203.0.113.18", "10.20.16.20"]
    dst:        ["172.16.10.10", "172.16.10.11", "172.16.10.12"]   # Phantom Lab DMZ hosts
    spt:      ["49152", "51234", "57890", "60123"]
    dpt:      ["443", "80"]
    proto:      ["6"]
    request:           ["/", "/api/v1/users", "/static/css/app.css"]
    requestMethod:        ["GET", "POST"]
    httpStatusCode:   ["200", "302", "404", "500", "503"]
    responseTimeMs: ["12", "45", "120", "1200"]
    backendServer: ["PHSRV-APP01", "PHSRV-WEB01", "PHSRV-FS01"]
    backendStatusCode: ["200", "500"]
    backendResponseTimeMs: ["8", "32", "100", "1100"]
    poolName:     ["web_pool", "api_pool"]
    poolMember:   ["PHSRV-APP01:8080", "PHSRV-WEB01:8080"]
    virtualServer: ["vs_https", "vs_http"]
    out:    ["480", "1024", "4096"]
    in: ["240", "12480", "1280"]
```

**Note**: if your XSIAM tenant doesn't field-map LB telemetry, you can skip this class by uninstalling the LB data source from the Marketplace temporarily, or by editing this skill to remove the LB recipe. LB events still ingest as raw rows but won't have a parser unless you write one.

---

### VPN

Authentication + session + geo + MFA. ~16 fields. The perimeter identity log.

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[<entry>].vendor>
  product: <stack[<entry>].product>
  count:    100
  interval: 1
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    suser:                  ["jaljuhani"]           # ONE person: login, home address and session address together
    src:                ["77.31.81.27"]           # the home_ip of jaljuhani
    act:                ["login_success", "login_failure", "logout"]
    authenticationResult: ["success", "failed"]
    authenticationMethod: ["password", "mfa", "certificate", "saml"]
    errorCode:            ["AUTH_OK", "AUTH_FAILED", "INVALID_CREDENTIALS"]
    externalId:            ["sess-001", "sess-002", "sess-003"]
    assignedIp:           ["10.20.200.10"]   # her own workstation address, inside the VPN pool
    country:               ["SA", "US", "DE", "RU"]
    mfaMethod:            ["push", "totp", "sms", ""]
    mfaResult:            ["success", "failed", "skipped"]
    cefSeverity:              ["informational", "medium", "high"]
    sessionDuration:      ["3600", "14400", "0"]
```

---

### Cloud (GCP / AWS / Azure equivalent)

Actor identity + API call + resource targeting + IAM activity + auth method. ~19 fields. Cloud audit telemetry — what the operator typically needs for cloud breach detection.

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[<entry>].vendor>
  product: <stack[<entry>].product>
  count:    100
  interval: 1
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    principalEmail:    ["data-export-svc@phantom-lab-prod.iam.gserviceaccount.com"]   # <project_id> from organization_get section=cloud
    src:      ["192.0.2.42", "188.55.20.5", "203.0.113.18"]   # 188.55.20.5 = the office NAT (egress.ruh_nat)
    country:       ["US", "SA", "RU"]
    act:        ["google.iam.admin.v1.CreateServiceAccount",
                    "google.iam.admin.v1.CreateServiceAccountKey",
                    "google.cloud.resourcemanager.v1.SetIamPolicy",
                    "storage.objects.get",
                    "compute.instances.start"]
    apiEndpoint:  ["iam.googleapis.com", "storage.googleapis.com",
                    "compute.googleapis.com"]
    requestMethod:    ["projects.serviceAccounts.create",
                    "projects.setIamPolicy", "objects.get"]
    operation:     ["create", "delete", "update", "list", "get"]
    resourceName: ["projects/phantom-lab-prod/serviceAccounts/data-export-svc@..."]
    resourceType: ["serviceAccount", "iamPolicy", "storageObject", "instance"]
    resourceId:   ["sa-001", "policy-002", "obj-003"]
    suser:      ["data-export-svc@phantom-lab-prod.iam.gserviceaccount.com"]
    keyId:     ["8f3a91d2c4b7e5a8d6f9b2c1e4a7d3f5b8c2e9a1"]
    authenticationMethod: ["oauth_token", "service_account_key", "user_credential"]
    cefSeverity:      ["informational", "medium", "high", "critical"]
    actionStatus: ["SUCCESS", "ERROR"]
    requestClientApplication: ["google-cloud-sdk/470.0.0", "python-requests/2.31.0"]
```

---

### SaaS (M365 / Workspace equivalent)

Identity + auth + app activity + email rules + file activity. ~18 fields. Modern identity-first attack surface.

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[<entry>].vendor>
  product: <stack[<entry>].product>
  count:    100
  interval: 1
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    suser:                  ["noura.alharbi@phantom.lab"]
    src:                ["144.86.80.11", "192.0.2.42"]   # first = the home_ip of nalharbi
    country:               ["SA", "US", "RU"]
    act:                ["login_success", "consent_to_application",
                            "new-inboxrule", "FileDownloaded",
                            "add_oauth2permissiongrant"]
    operation:             ["UserLoggedIn", "Consent to application",
                            "New-InboxRule", "FileDownloaded"]
    appDisplayName:        ["InvoicePro Sync"]
    scope:                 ["User.Read", "offline_access", ""]
    authenticationMethod: ["password", "mfa", "oauth_token"]
    externalId:            ["sess-A1B2C3D4"]
    fname:             ["report.xlsx", "policy.docx", ""]
    request:              ["/personal/noura_alharbi_phantom_lab/Documents", ""]
    out:                 ["180000", "245000", "0"]
    cefSeverity:              ["informational", "medium", "high"]
```

---

## Execution

The agent's runbook for the skill:

1. **Pre-flight** — call `data_sources_installed_as_vendors`, parse `vendors[]`. If empty, stop and tell the operator to install a data source first. For each entry, look up the field-template recipe by `data_source_class`.
2. **Parallel dispatch** — call `xlog.create_data_worker` once per stack entry, concurrently. Each worker is a 100-event 10-second burst targeting that vendor/product. All workers run in the background; the agent doesn't await each one before firing the next.
3. **Wait briefly** — give workers 12-15 seconds of wall-clock time to complete (the burst is 10s, plus a small buffer for ingestion).
4. **Verify** — call `xlog.list_workers` to confirm all workers reached `Stopped` status without errors. Optionally call `xsiam.get_issues` or query the XSIAM tenant directly to confirm row counts in each dataset.
5. **Summarize** — report per-class event count + dataset name (per the operator's stack mapping) + any classes that were skipped (unsupported category) or failed (worker error).

## Verification

After the skill finishes, the operator should see (within ~1 minute of skill completion):

| Indicator | Where to check |
|---|---|
| Per-dataset row count ≈100 | XSIAM Settings → Data Sources → each ingestion source |
| Field-mapping UI no longer empty | XSIAM Settings → Data Sources → click into a source → Fields tab |
| All field templates show ≥3 distinct values per field, except the identity fields (user, host, address), which carry one person's values | Field-mapping preview, scan for the field types the parser sees |
| No worker errors | `xlog.list_workers` should show all `Stopped` status |

If any dataset is still empty after the skill: check the operator's XSIAM ingestion broker config (the broker might not be enabled or might be filtering on something the synthetic data doesn't match), and check `xsiam.get_issues` for any ingestion-side error.

## When to re-run

- **After adding a new data source to the stack** — re-run the skill; only the new source's worker needs to fire (the agent can detect "this dataset already has rows" and skip)
- **After the operator edits this skill's field templates** — re-run to populate the dataset with the new field shapes (XSIAM's parser will see the new fields on subsequent ingest)
- **NOT routine maintenance** — this is a bootstrap utility; running it monthly just adds noise to the tenant. Once datasets are field-mapped, real telemetry takes over.

## Tear-down

The skill creates N data workers (one per stack entry). After the bootstrap completes:

```yaml
xlog.list_workers:
  # confirms all are Stopped
xlog.kill_worker:
  worker_id: <each — only if any are still running past the burst window>
```

The events are already ingested into XSIAM; tear-down doesn't unsend them. If the operator wants to mark the bootstrap events as test/non-production, they can use XSIAM's tagging on the dataset to filter them out of real-incident triage.

## Adapting per deployment

The attacker-side example values in each recipe (`192.0.2.42`, `203.0.113.18`) are illustrative. Every company identity (users, hosts, servers, mail domain, cloud project) comes from the active organization (`organization_get`); the skill just defines the *fields*. To change who appears in the seeded rows, edit the organization (`organization_update`), not the recipes. Agent's recipes are authoritative once the skill saves.

If a class isn't covered in the templates above (e.g. operator has an `IDS` or `MDR` class in their stack), the agent should fall back to a minimal fields recipe (`src_ip`, `dst_ip`, `action`, `severity`, `alert_name`) and emit a warning that the class was skipped from the curated templates. Editing this skill MD to add a new class section is the right way to extend coverage.
