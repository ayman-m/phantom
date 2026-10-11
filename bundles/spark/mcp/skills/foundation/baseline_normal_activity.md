---
name: baseline_normal_activity
displayName: Baseline normal activity
category: foundation
description: 'Generates realistic BENIGN day-in-the-life telemetry — business-hours VPN sign-ins, routine web browsing through the proxy, ordinary allowed firewall flows, successful MFA, and normal WAF 200s. This is the noise floor every attack scenario needs: a detection tuned only on attack traffic has never seen benign traffic and will false-positive in production. Vendor-agnostic — resolves vendor/product from the operator''s installed data sources at runtime. Use when the operator asks for "normal activity", "baseline traffic", "benign logs", "background noise", "a quiet day", or wants to measure a rule''s false-positive rate. Also run this BEFORE an attack scenario so the attack stands out against real background instead of an empty dataset.'
icon: groups
source: platform
loadingMode: on-demand
locked: false
attack: []
---

# Skill: Baseline normal activity

## Category

foundation

## Purpose

Every other skill in `scenarios/` generates an attack. Run those alone and the dataset is
100% malicious — which is not a SOC, it is a shooting range. Three concrete problems follow:

1. **Detections can't be tuned.** A rule that fires on "a VPN login from a new country"
   looks perfect when the only logins in the dataset are the attacker's. Add 400 benign
   logins from travelling employees and the same rule's false-positive rate becomes visible.
2. **Analysts can't practise triage.** Triage is the skill of separating one bad thing from
   a thousand boring ones. With no boring ones there is nothing to practise.
3. **Volume-based analytics never calibrate.** Anomaly rules that key on "unusual volume"
   or "rare process" need a baseline to be unusual *relative to*.

This skill produces that baseline. It is deliberately **boring** — nothing here should fire
a detection. If something does fire, that is a finding about the rule, not about this skill.

**When to run:**
- Once per environment before the first attack scenario, to seed a background.
- Continuously alongside an attack run, so the attack has to be *found* rather than *read*.
- Standalone, to measure a rule's false-positive rate over benign traffic.

## MITRE ATT&CK Tactics

Not applicable — this is benign telemetry by design. No technique should map.

## Data classes used

Every stage is **optional and independent**. Run whichever classes the operator actually has
installed; skip the rest without complaint. There is no "required" class — a baseline of
firewall-only traffic is still a useful baseline.

| Stage | Data class | What it models |
|---|---|---|
| 1 | `vpn` | Employees signing in for the workday |
| 2 | `saas` | Successful MFA + routine SaaS sign-ins |
| 3 | `proxy` | Ordinary web browsing to business + consumer sites |
| 4 | `firewall` | Routine allowed east-west and outbound flows |
| 5 | `waf` | Legitimate application traffic returning 200s |

## Pre-flight

Resolve `<destination>` separately: call `log_destinations_list` once and use the operator's
default (or first) destination unless a specific one is requested — destination selection is
independent of the data-source vendor/product lookup below.

Call `data_sources_installed_as_vendors` once. Group `vendors[]` by `data_source_class` into a
category → entry lookup. For each stage below, if its class has **no** installed entry, skip
that stage silently and continue — unlike the attack scenarios, a missing class here is not an
error and does **not** warrant stopping. At the end, tell the operator which stages ran and
which were skipped for lack of an installed data source.

If `vendors[]` is empty entirely, stop and tell the operator: no data sources are installed —
install at least one from the Marketplace before any log generation can run.

The recipes reference entries as `<stack[<class>].vendor>` / `.product`. The wire format is always `CEF` (delivery doctrine).
Call `data_sources_get_schema(<entry>.data_source_id)` per stage when a recipe needs
`schema_override`. **Never hardcode vendor names.**

## Realism rules (what makes this baseline believable)

These are the difference between "benign traffic" and "random noise that happens not to be an
attack". Apply all five:

1. **Business-hours weighting.** Real corporate traffic is diurnal. Concentrate volume between
   08:00–18:00 local, with a lunch dip around 12:00–13:00 and a long tail into the evening.
   Use `interval` to spread events rather than firing them all in one burst.
2. **Zipf-distributed users.** A handful of users generate most events; most users generate
   few. Repeat the top 3–5 usernames far more often than the rest of the list.
3. **Overwhelmingly successful outcomes.** Benign auth is ~95–99% success. Include a *small*
   number of ordinary failures — a mistyped password, an expired session — because a dataset
   with a 100% success rate is itself anomalous and will skew any ratio-based rule.
4. **Internal RFC1918 sources, plausible external destinations.** Employees browse from
   `10.x`/`192.168.x` to real-world-shaped public destinations. Do not reuse the documentation
   ranges (`192.0.2.x`, `198.51.100.x`, `203.0.113.x`) that the attack scenarios use for
   adversary infrastructure — keeping the ranges disjoint is what lets an analyst tell the two
   apart, and lets you measure a rule cleanly.
5. **Ordinary user agents and apps.** Current Chrome/Edge/Safari on Windows and macOS. No
   `curl`, no `sqlmap`, no `python-requests` — those belong in the recon scenarios.

---

### Stage 1 — Workday VPN sign-ins — ~120 events over 60 minutes

Employees connecting at the start of the day and reconnecting after drops. Nearly all succeed.

**Data class:** `vpn`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[vpn].vendor>
  product: <stack[vpn].product>
  count:    120
  interval: 30
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    suser:          ["sarah.chen", "sarah.chen", "sarah.chen",
                    "m.okafor", "m.okafor", "j.lindqvist",
                    "d.rossi", "a.haddad", "priya.n", "t.yamamoto"]
    src:        ["203.0.113.200"]
    dst:        ["10.10.0.50"]
    assignedIp:   ["10.20.14.31", "10.20.14.52", "10.20.15.10", "10.20.15.77"]
    act:        ["login", "login", "login", "login", "logout"]
    actionStatus: ["success", "success", "success", "success", "success",
                    "success", "success", "success", "success", "failure"]
    authenticationMethod:   ["certificate", "saml", "saml"]
    country:       ["GB", "GB", "GB", "DE", "AE"]
    sessionDuration: ["1800", "3600", "7200", "14400"]
    out:     ["120000", "480000", "2400000"]
    in: ["340000", "1200000", "8600000"]
```

**Why this is benign:** one corporate egress IP, a stable user set, `success` dominating ~9:1,
and countries consistent with a UK-based org with staff in DE/AE. Nothing here is impossible-
travel — the same user never appears from two distant countries close together. *(If you want
to test an impossible-travel rule, that is `bruteforce_vpn_to_lateral`, not this skill.)*

---

### Stage 2 — Routine MFA + SaaS sign-ins — ~200 events over 60 minutes

The identity layer's ordinary day: push approvals, remembered devices, a few timeouts.

**Data class:** `saas`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[saas].vendor>
  product: <stack[saas].product>
  count:    200
  interval: 18
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    suser:          ["sarah.chen", "sarah.chen", "m.okafor", "m.okafor",
                    "j.lindqvist", "d.rossi", "a.haddad", "priya.n",
                    "t.yamamoto", "svc_backup"]
    src:        ["10.20.14.31", "10.20.14.52", "10.20.15.10", "203.0.113.200"]
    eventType:    ["authentication", "authentication", "authentication", "enrollment"]
    mfaMethod:        ["duo_push", "duo_push", "duo_push", "passcode", "webauthn"]
    result:        ["success", "success", "success", "success", "success",
                    "success", "success", "success", "denied", "timeout"]
    app:   ["Microsoft 365", "Salesforce", "Workday", "GitHub", "Zoom"]
    device:        ["iPhone 15", "Pixel 8", "MacBook Pro", "ThinkPad X1"]
    os:            ["iOS 17.4", "Android 14", "macOS 14.4", "Windows 11"]
    geoLocation:      ["London, GB", "London, GB", "Manchester, GB", "Berlin, DE"]
```

**Why this is benign:** `denied`/`timeout` appear at ~1 in 10, which is the real-world rate for
a user who dismissed a push by accident. A push-fatigue detection should NOT fire — that
pattern needs many rapid denials for one user, which this distribution does not produce.

---

### Stage 3 — Ordinary web browsing — ~400 events over 60 minutes

The single highest-volume source in most orgs. Business SaaS, news, and a bit of shopping.

**Data class:** `proxy`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[proxy].vendor>
  product: <stack[proxy].product>
  count:    400
  interval: 9
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    suser:          ["sarah.chen", "sarah.chen", "sarah.chen", "m.okafor",
                    "m.okafor", "j.lindqvist", "d.rossi", "a.haddad", "priya.n"]
    src:        ["10.20.14.31", "10.20.14.52", "10.20.15.10", "10.20.15.77"]
    request:           ["https://outlook.office.com/mail/",
                    "https://teams.microsoft.com/",
                    "https://company.sharepoint.com/sites/hr",
                    "https://github.com/orgs/acme/repositories",
                    "https://www.bbc.co.uk/news",
                    "https://docs.google.com/spreadsheets/",
                    "https://www.linkedin.com/feed/",
                    "https://stackoverflow.com/questions/",
                    "https://www.amazon.co.uk/",
                    "https://zoom.us/j/"]
    requestMethod:   ["GET", "GET", "GET", "GET", "POST"]
    httpStatusCode:   ["200", "200", "200", "200", "200", "204", "304", "302", "404"]
    urlCategory:  ["business", "business", "collaboration", "news",
                    "technology", "social-networking", "shopping"]
    act:        ["allowed", "allowed", "allowed", "allowed", "blocked"]
    requestClientApplication:    ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"]
    out:     ["1200", "2400", "8600", "15000"]
    in: ["24000", "86000", "340000", "1200000", "4800000"]
```

**Why this is benign:** `bytes_received` >> `bytes_sent` throughout — that ratio is what normal
browsing looks like. The exfiltration scenarios invert it. The occasional `blocked` is an
ordinary category-policy hit (shopping on a restricted profile), not a threat block.

---

### Stage 4 — Routine allowed firewall flows — ~500 events over 60 minutes

Background network chatter: DNS to internal resolvers, HTTPS out, SMB to file servers.

**Data class:** `firewall`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[firewall].vendor>
  product: <stack[firewall].product>
  count:    500
  interval: 7
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["10.20.14.31", "10.20.14.52", "10.20.15.10",
                    "10.20.15.77", "10.10.30.10", "10.10.30.20"]
    dst:        ["10.10.0.53", "10.10.30.10", "10.10.30.40",
                    "142.250.187.206", "20.190.159.4", "140.82.121.4"]
    spt:      ["49152", "51234", "57890", "60123", "62456"]
    dpt:      ["443", "443", "443", "53", "445", "3389", "80"]
    proto:      ["tcp", "tcp", "tcp", "udp"]
    act:        ["allow", "allow", "allow", "allow", "allow", "deny"]
    app:           ["ssl", "ssl", "dns", "smb", "ms-rdp", "web-browsing"]
    sessionType: ["established", "established", "established", "closed"]
    out:     ["1400", "4800", "12000", "48000"]
    in: ["8600", "34000", "180000", "960000"]
    packets:       ["12", "48", "220", "1400"]
    country:       ["US", "IE", "GB", "NL"]
```

**Why this is benign:** ~5:1 allow-to-deny, a stable internal source set, and public
destinations that resolve to Google/Microsoft/GitHub ranges. No single source touches many
destinations on one port (that is the horizontal-scan signature in `trigger_network_analytics_alerts`), and
no source sweeps many ports on one host (the vertical-scan signature).

---

### Stage 5 — Legitimate application traffic — ~250 events over 60 minutes

Real users using the web app the WAF fronts. Overwhelmingly 200s, no attack signatures.

**Data class:** `waf`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[waf].vendor>
  product: <stack[waf].product>
  count:    250
  interval: 14
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["10.20.14.31", "10.20.15.10", "82.14.221.6", "86.129.44.190"]
    dst:        ["10.10.30.10"]
    dpt:      ["443"]
    proto:      ["6"]
    request:           ["/", "/login", "/dashboard", "/api/v1/profile",
                    "/api/v1/orders?page=2", "/static/app.js",
                    "/static/style.css", "/search?q=invoice",
                    "/reports/monthly", "/health"]
    requestMethod:        ["GET", "GET", "GET", "GET", "POST"]
    httpStatusCode:   ["200", "200", "200", "200", "200", "304", "302", "401"]
    act:        ["allow", "allow", "allow", "allow", "allow"]
    requestClientApplication:    ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"]
    out:     ["800", "1400", "3200"]
    in: ["4800", "18000", "64000", "240000"]
    threatScore:  ["0", "0", "0", "5"]
```

**Why this is benign:** every `action` is `allow`, `threat_score` sits at 0, and the URLs are
ordinary application paths with no injection payloads or traversal sequences. The single `401`
is a user hitting a page before login — routine, not credential stuffing.

---

## Execution

1. **Pre-flight** — resolve destination + installed classes (see above).
2. **Fire the stages you have data sources for, in parallel.** Use separate
   `xlog.create_data_worker` calls — one per stage. Space the calls **3–4 seconds apart**:
   worker IDs are timestamp-second-granular and a faster loop makes one worker clobber another.
3. **Report** which stages ran, which were skipped, and the worker IDs.

Total volume with all five stages: ~1,470 events over an hour. Scale `count` up or down
together across stages to keep the inter-class ratios realistic — proxy and firewall should
always dominate; VPN and MFA should always be the smallest.

## Sustained baselines: use phantom jobs, not immortal workers

A one-shot baseline decays. Analytics detectors profile against a rolling 30-day window, so the
benign noise floor has to be **refreshed every day** — and rarity detectors only fire on hosts
that HAVE a benign history (a brand-new attacker host with zero baseline
is invisible to rarity/single-event detectors). The mechanism for this is **phantom jobs**, not
long-running workers:

```yaml
jobs_create:
  name: baseline-atkpool-web
  schedule: "13 6-18 * * *"        # hourly during business hours
  timezone: Asia/Riyadh            # the operator's timezone, not UTC
  action:
    type: tool_call
    name: xlog.create_data_worker
    args:
      type: CEF
      vendor: <stack[firewall].vendor>
      product: <stack[firewall].product>
      count: 40                    # one BOUNDED burst per firing...
      duration_seconds: 120        # ...that finishes in ~2 minutes
      max_events: 40
      destination: logdest:<id>
      schema_override: [...]
      observables_dict: {...}      # pinned persona hosts, e.g. WS-LAB-10..17
```

Design rules (a pool of 8 hosts at roughly 110-140
events/host/day works well):

1. **Bounded bursts, not forever-workers.** The runtime has a one-worker slot; a worker that
   never ends blocks every other job. Each firing should run `count = max_events` events over
   ~2 minutes and exit.
2. **Stagger the schedules.** Give each job its own minute (`13 6-18 * * *`, `41 */2 * * *`,
   `53 */3 * * *`) so bursts don't collide on the worker slot.
3. **Pin a stable host pool.** The same hostnames/IPs every day (e.g. WS-LAB-10..17 /
   10.20.63.10-17) — continuity is what builds each host's 30-day profile. Future "attacker"
   hosts should come FROM this pool: pre-seeded benign history is what makes their later
   anomaly detectable as rare/uncommon.
4. **One job per traffic class** (web, DNS, internal east-west, per-vendor) rather than one
   monolithic job — you can tune or disable classes independently.
5. Business-hours weighting still applies: schedule dense inside 08:00-18:00 local, sparse or
   absent overnight.

## Verification

**Quota discipline is mandatory** — every tenant query below uses BOTH a narrowing `filter`
and a `limit`, and prefers a `comp` aggregate over returning rows. One aggregate costs about
0.0003 compute units; returning thousands of raw rows costs orders of magnitude more.

Confirm landing with ONE aggregate per dataset — never a raw-row dump:

```
config timeframe = 1h
| dataset = <dataset_name>
| comp count() as events
| limit 1
```

To sanity-check the benign shape without pulling volume, aggregate by outcome:

```
config timeframe = 1h
| dataset = <dataset_name>
| comp count() as n by action
| limit 10
```

Expect `allow`/`success` to dominate. If denials or failures lead, the recipe was mis-seeded.

**Do NOT** run `| fields *` or an unbounded `dataset = X | limit 1000` to "look at the data" —
that is the single most expensive thing you can do on the tenant and it answers a question the
aggregate already answered.

## Tear-down

```
xlog.list_workers()
xlog.kill_worker(worker_id="<each id from this run>")
```

Baseline workers are long-running by design. Always kill them when the exercise ends, or they
keep emitting at the broker indefinitely. (For a baseline that should persist beyond the
exercise, prefer scheduled jobs with bounded bursts — see "Sustained baselines" above — and
manage them with `jobs_list` / `jobs_delete` instead.)

## Adapting per deployment

- **Swap the user list** for names matching the operator's directory — the baseline is far more
  convincing during a demo when the usernames are recognisable.
- **Match the internal ranges** to the operator's real subnets. Keep them disjoint from the
  documentation ranges the attack scenarios use.
- **Shift the country mix** to the operator's actual footprint. A UK-only org with logins from
  five continents is itself an anomaly.
- **Scale by org size.** ~1,500 events/hour models a small office. Multiply `count` across all
  stages proportionally for a larger estate; keep the inter-class ratios fixed.
