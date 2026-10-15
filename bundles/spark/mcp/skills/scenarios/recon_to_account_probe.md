---
name: recon_to_account_probe
displayName: External recon scan
category: scenarios
description: 'Four-stage external reconnaissance chain. Stage 1: firewall sees port scan from one source against multiple internal IPs. Stage 2: proxy detects directory-traversal probes against discovered web apps. Stage 3: WAF detects payload-based recon (sqlmap signatures). Stage 4: account probing follow-on at the VPN portal once usernames are discovered. Vendor-agnostic — agent resolves vendor/product from the operator''s installed data sources at runtime. Triggers 4 XSIAM rules: Account Probing, C2 Beaconing (slow-burn variant), Malicious URL via proxy, SQL Injection Attempt. Use when you want to demonstrate end-to-end perimeter detection of pre-attack reconnaissance.'
icon: search
source: platform
loadingMode: on-demand
locked: false
attack:
  - 'TA0043: Reconnaissance (T1595.001 Scanning IP Blocks, T1595.002 Vulnerability Scanning, T1589.002 Email Addresses)'
  - 'TA0001: Initial Access (T1190 Exploit Public-Facing Application)'
  - 'TA0006: Credential Access (T1110.003 Password Spraying)'
---

# Skill: External recon → Web app discovery → Account probe

## Category

scenarios

## Attack Type

Pre-exploitation reconnaissance — the phase BEFORE a real attack, where the adversary is mapping the attack surface. Most SOCs ignore recon traffic ("it's just internet noise") and only respond after the actual exploit. This skill demonstrates that recon IS detectable, and detecting it provides early warning days or weeks before a breach.

## MITRE ATT&CK Tactics

- TA0043: Reconnaissance (T1595.001 Scanning IP Blocks, T1595.002 Vulnerability Scanning, T1589.002 Email Addresses)
- TA0001: Initial Access (T1190 Exploit Public-Facing Application)
- TA0006: Credential Access (T1110.003 Password Spraying)

## XSIAM analytics rules triggered

| # | Rule | Stage |
|---|---|---|
| 1 | Account Probing — single source attempting many distinct accounts | Stage 4 |
| 7 | C2 Beaconing (variant: slow recon-style periodic touches) | Stage 1 |
| 8 | Malicious URL via proxy (directory traversal patterns) | Stage 2 |
| 15 | SQL Injection Attempt | Stage 3 |

## Data classes used

| Stage | Data class | If missing |
|---|---|---|
| 1 | `firewall` | Required |
| 2 | `proxy` | Substitute with `firewall` (loses URL/payload context) |
| 3 | `waf` | Required for Stage 3 |
| 4 | `vpn` | Substitute with M365/`saas` sign-in failures if no VPN exposed |

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
3. For each stage whose class is `MISSING` (and has no substitute in the table), say this to the operator, with the class and stage filled in: "No installed data source covers the `<class>` class, so I am skipping Stage <N> (<stage name>). I will not generate it with a generic schema. Install a `<class>` data source from the Marketplace to include it." Then create NO worker for that stage: not with a generic schema, not with another class's schema, not with a guessed vendor/product. Continue with the stages whose classes are covered. If every stage is `MISSING`, stop after saying it. Substitutions from the table apply first: `proxy` missing means use the `firewall` entry for Stage 2; `vpn` missing means use the `saas` sign-in failures for Stage 4. Say when you substitute.
4. In your final report, list every stage you skipped or substituted and which of the alerts above will therefore not fire.

## Pre-flight: read the organization

The scan target is the organization's DMZ. Call `organization_get(section="hosts", filter="role=dmz")` for the public web server (PHDMZ-WEB01), the mail gateway (PHDMZ-MAIL01) and the VPN gateway (PHDMZ-VPN01), `organization_get(section="networks")` for the DMZ block (`172.16.10.0/24` on Phantom Lab), and `organization_get(section="accounts", limit=100)` for the logins the Stage 4 probe guesses. Do not invent a host, subnet or account. If the organization has no DMZ web host or no VPN gateway, tell the operator and offer `organization_update` instead.

## Narrative thread

- **Attacker source IP:** `192.0.2.42` (TEST-NET-2 documentation range — replace with a documented threat-intel-sourced IP for real exercises). The attacker is outside the organization.
- **Internal IP range scanned (Stage 1):** the organization's DMZ block (`172.16.10.0/24` on Phantom Lab). The 10 scanned addresses include the real DMZ hosts (PHDMZ-WEB01 `172.16.10.10`, PHDMZ-MAIL01 `172.16.10.11`, PHDMZ-VPN01 `172.16.10.12`) and unused addresses of the same block.
- **Discovered web app (after Stage 1 finds open 443):** PHDMZ-WEB01 at `172.16.10.10` (public address `egress.dmz_public.PHDMZ-WEB01`, `151.254.90.10` on Phantom Lab)
- **VPN portal (Stage 4 target):** PHDMZ-VPN01 (`172.16.10.12`, public address `egress.dmz_public.PHDMZ-VPN01`, `151.254.90.12` on Phantom Lab)
- **Probed account list:** common admin defaults + logins of the organization (staff, administrators, service accounts) from `section=accounts`
- **Wall-clock time:** Stage 1 ~25 min (slow scan to evade thresholds). Stage 2 ~10 min (post-discovery enum). Stage 3 ~12 min (payload recon). Stage 4 ~15 min (account probing). Total: ~62 min — recon is patient.

---

### Stage 1 — Port scan / network discovery — ~250 events over 25 minutes

The attacker scans the public-facing IP range. The firewall sees ~250 inbound connection attempts to varying ports from a single source. Most are denied; a handful (the ones to actual open ports) get through to the destination services. This is intentionally LOW-RATE — fast scans get caught by trivial rate-limit detections, but a scan paced at 1 connection per 6 seconds slips below most thresholds.

**Data class:** `firewall`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[firewall].vendor>
  product: <stack[firewall].product>
  count:    250
  interval: 6
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["192.0.2.42"]
    dst:        ["172.16.10.1", "172.16.10.5", "172.16.10.10",
                    "172.16.10.11", "172.16.10.12", "172.16.10.20",
                    "172.16.10.42", "172.16.10.50", "172.16.10.100",
                    "172.16.10.200"]   # 10 addresses of the organization's DMZ block, including its real hosts
    dpt:      ["22", "23", "25", "80", "110", "135", "139",
                    "143", "443", "445", "1433", "3306", "3389",
                    "5432", "5985", "8080", "8443", "9000"]
    spt:      ["49152", "49251", "49380", "50127", "50882"]
    proto:      ["6"]
    act:        ["deny", "deny", "deny", "allow", "deny"]
    app:           ["unknown", "ssl", "ssh", "http"]
    out:    ["64", "0", "120"]
    in: ["0", "0", "240", "1240"]
    country:       ["unknown"]
    tcpFlags:      ["SYN", "SYN", "SYN-ACK"]
    threatScore:  ["35", "60"]
```

**Field semantics:**
- `dst_ip` covers 10 addresses in the organization's DMZ block — the scan is sweeping the subnet
- `dst_port` covers 18 well-known service ports — characteristic port-knock pattern
- `action: deny` predominates (firewall blocks most), with a few `allow`s for ports that have services listening (e.g. 443 to PHDMZ-WEB01 at 172.16.10.10)
- `tcp_flag: SYN` for connection attempts; `SYN-ACK` for the few that get through
- `bytes_sent/received: 0 / 0` for denied (firewall returns nothing); larger for allowed

**Why this fires Rule #7 (slow-burn C2 / scanning variant):** the rule isn't typically named "port scan detected" in modern SIEMs (those are noisy). What DOES fire is a periodic-connection-pattern detection: same source, periodic outbound (~250 connections at ~6s intervals = visible periodicity) — matches the C2-beaconing detection family even though the activity is recon, not actual C2.

---

### Stage 2 — Directory-traversal & path-enumeration — ~60 events over 10 minutes

After Stage 1 found the web app on PHDMZ-WEB01 (`172.16.10.10:443`), the attacker probes for known sensitive paths: `.git/config`, `.env`, `phpmyadmin/`, `wp-admin/`, etc. Most return 404 or 403; a few interesting ones (e.g., `/.well-known/`, `/robots.txt`, `/sitemap.xml`) return 200 and leak structure.

**Data class:** `proxy`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[proxy].vendor>
  product: <stack[proxy].product>
  count:    60
  interval: 10
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["192.0.2.42"]
    dst:        ["<web server DMZ address: 172.16.10.10 for PHDMZ-WEB01>"]
    dpt:      ["443"]
    request:           ["/.git/config", "/.env", "/.svn/entries",
                    "/phpmyadmin/", "/wp-admin/", "/wp-login.php",
                    "/admin/", "/admin/login.php", "/administrator/",
                    "/phpinfo.php", "/server-status", "/server-info",
                    "/.well-known/security.txt", "/robots.txt",
                    "/sitemap.xml", "/api/v1/users", "/api/v1/admin",
                    "/swagger/", "/swagger.json", "/api-docs",
                    "/backup.sql", "/db.sql", "/config.php.bak",
                    "/index.php?page=../../../../etc/passwd",
                    "/files?path=....//....//....//etc/passwd"]
    requestMethod:        ["GET"]
    httpStatusCode:   ["404", "403", "200", "301"]
    requestClientApplication:    ["Mozilla/5.0 (X11; Linux x86_64)",
                    "curl/7.81.0",
                    "Mozilla/5.0 (compatible; Nuclei/3.0; +https://nuclei.projectdiscovery.io)",
                    "ffuf/2.0.0"]
    act:        ["allow", "block"]
    attackType:   ["directory-traversal", "scanner-fingerprint",
                    "common-vulnerabilities", "path-traversal"]
    out:    ["480", "640"]
    in: ["240", "1280", "4096"]
    cat:      ["uncategorized", "newly-registered-domain",
                    "scanner"]
    threatCategory: ["suspicious"]
    threatScore:    ["72", "85"]
```

**Field semantics:**
- `url` shows the canonical "common probes" list — `.git/config` (often left exposed), `.env` (database creds in DevOps mistakes), `wp-admin/` (WordPress fingerprint), `swagger/` (API documentation that leaks endpoints), and explicit traversal patterns (`....//....//....//etc/passwd`)
- `user_agent` includes specific scanner fingerprints — `Nuclei`, `ffuf` are well-known security testing tools
- `threat_category: suspicious` — modern proxies enrich with category based on the URL pattern; `directory-traversal` / `scanner-fingerprint` push the score above 70

**Why this fires Rule #8:** the volume + URL category (`scanner` / `directory-traversal`) + suspicious-pattern matches cross the "malicious URL access" threshold. Most SIEMs key on (a) ≥10 distinct suspicious URLs from one source in 10 min, or (b) any single URL matching a high-confidence pattern (e.g. `etc/passwd`).

---

### Stage 3 — WAF-visible payload recon — ~40 events over 12 minutes

The attacker shifts from path enumeration to payload probing. They run sqlmap-like signatures against parameters they discovered in Stage 2 (`?id=`, `?user=`, `?search=`, etc.). Different from `web_app_to_webshell_to_exfil` Stage 1 — that's high-volume blast probing; this is targeted, ~40 carefully-chosen payloads from one source.

**Data class:** `waf`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[waf].vendor>
  product: <stack[waf].product>
  count:    40
  interval: 18
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["192.0.2.42"]
    dst:        ["<web server DMZ address: 172.16.10.10 for PHDMZ-WEB01>"]
    spt:      ["49152", "51234", "57890"]
    dpt:      ["443"]
    proto:      ["6"]
    request:           ["/api/v1/users?id=1", "/api/v1/users?id=1'",
                    "/api/v1/users?id=1%20AND%201%3D1--",
                    "/api/v1/users?id=1%20OR%20'a'%3D'a",
                    "/login.php?username=admin'--&password=x",
                    "/search.php?q=%3Cscript%3Ealert(1)%3C/script%3E",
                    "/api/v1/profile?email='%3BSELECT%20pg_sleep(5)--",
                    "/feed.php?id=-1%20UNION%20SELECT%20null,version(),null--"]
    requestMethod:        ["GET", "POST"]
    httpStatusCode:   ["403", "200", "500"]
    requestClientApplication:    ["sqlmap/1.7.2#stable (https://sqlmap.org)",
                    "Mozilla/5.0 (X11; Linux x86_64)",
                    "Mozilla/5.0 (compatible; w3af.org)"]
    act:        ["block", "alert", "allow"]
    attackType:   ["sql-injection", "xss", "command-injection"]
    attackSeverity: ["high", "medium"]
    ruleId:       ["942100", "942130", "941100", "942180"]
    ruleName:     ["SQL Injection Attack: Common Injection Testing",
                    "SQL Injection Attack Detected via libinjection",
                    "XSS Attack Detected"]
    out:     ["480", "640"]
    in: ["240", "1280", "4096"]
    threatScore:  ["72", "85", "92"]
```

**Field semantics:** similar to the SQLi probe block in `web_app_to_webshell_to_exfil`, but lower volume (40 events vs 80) and broader payload variety (SQLi + XSS + command-injection probes). The `user_agent` mix shows the attacker rotating tools.

**Why this fires Rule #15:** any modern WAF detects ≥10 SQLi signatures from one source in <30 min. The 40-event burst within 12 min is well above the typical threshold.

---

### Stage 4 — Account probing at the VPN portal — ~80 events over 15 minutes

The attacker has discovered usernames from Stage 2 (e.g., `/api/v1/users` returned 401 with a JSON body like `{"error": "user 'admin' requires authentication"}`). They now probe the VPN auth endpoint with the usernames they discovered, looking for one that doesn't immediately rate-limit.

**Data class:** `vpn`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[vpn].vendor>
  product: <stack[vpn].product>
  count:    80
  interval: 11
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:                ["192.0.2.42"]
    suser:                  ["admin", "administrator", "root", "guest", "test",
                            "demo", "support", "helpdesk", "backup", "operator",
                            "service", "scanner", "audit", "compliance",
                            "manager", "director", "ceo", "cfo",
                            # 14 more: real logins from organization_get(section="accounts", limit=100),
                            # service accounts first. Phantom Lab example:
                            "svc-backup", "svc-sql", "svc-web", "svc-app",
                            "adm.ialkhalifa", "adm.malwadi",
                            "nalharbi", "kalotaibi", "aalzahrani", "salmutairi",
                            "falqahtani", "raldosari", "oalshehri", "halghamdi"]
    act:                ["login_failure"]
    authenticationResult: ["failed"]
    authenticationMethod: ["password"]
    errorCode:            ["AUTH_FAILED", "INVALID_CREDENTIALS",
                            "USER_NOT_FOUND"]
    cefSeverity:              ["medium"]
    country:               ["unknown"]
```

**Field semantics:**
- `user` — 32 distinct usernames from one source. `error_code: USER_NOT_FOUND` tells the attacker which usernames don't exist; `INVALID_CREDENTIALS` (vs `USER_NOT_FOUND`) is the leak that the username DOES exist (across the burst, expect `INVALID_CREDENTIALS` mostly for the real logins of the organization and `USER_NOT_FOUND` mostly for the generic guesses; the single worker draws each field independently, so this is the overall mix, not a per-user pairing)
- `src_ip: 192.0.2.42` — same source as Stages 1-3, completing the "one attacker, end-to-end recon" narrative

**Why this fires Rule #1:** classic account-probing pattern — 32 distinct users from one source in 15 min. Threshold is typically ≥10 users / 5 min from one source. This crosses it 3x over.

---

## Verification

| Indicator | Where to check |
|---|---|
| Beaconing alert / port-scan alert from `192.0.2.42` | XSIAM Issues |
| Suspicious URL alert: `.env` / `.git/config` / scanner UAs | XSIAM Issues |
| WAF alert: SQLi probes from same source | XSIAM Issues |
| Account-probing alert at VPN | XSIAM Issues |
| Pivotable: filter by `src_ip=192.0.2.42` to see all 4 stages | XQL: `config timeframe = 24h \| dataset = <dataset_name of the firewall entry> \| filter <its source-IP field> = "192.0.2.42" \| limit 20` |

## Tear-down

```yaml
xlog.list_workers:
xlog.kill_worker:
  worker_id: <each>
```

## Adapting per deployment

Replace `192.0.2.42` with a real threat-intel IP if the operator wants their TI integration enriched. The destination block, the web server, the VPN gateway and the probed logins always come from the active organization (`organization_get`); on another organization, read its own DMZ block and hosts.
