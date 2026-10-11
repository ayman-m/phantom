---
name: dns_tunneling_c2
displayName: DNS tunneling C2
category: scenarios
description: 'Three-stage covert C2 channel using DNS as the carrier. Stage 1: DGA-style high-entropy queries (sample / probe of attacker DNS infra). Stage 2: long-subdomain tunneling pattern carrying base32-encoded data over TXT/A queries. Stage 3: firewall confirms outbound TCP/53 or UDP/53 to known-bad name servers. Vendor-agnostic — agent resolves vendor/product from the operator''s installed data sources at runtime. Triggers 3 XSIAM rules: DGA-style High-Entropy DNS Queries, DNS Tunneling, C2 Beaconing.'
icon: vpn_key_off
source: platform
loadingMode: on-demand
locked: false
attack:
  - 'TA0011: Command and Control (T1071.004 DNS, T1572 Protocol Tunneling, T1568.002 Domain Generation Algorithms)'
---

# Skill: DNS tunneling C2

## Category

scenarios

## Attack Type

Covert command-and-control over DNS. Two patterns combined:
- **DGA (Domain Generation Algorithm)** — malware generates pseudo-random domains daily; only one is registered; the implant probes thousands of variants until a registered one resolves
- **Tunneling** — once a name server is found, request/response data is encoded into the subdomain (queries) and TXT/A response records (replies). 60+ chars of base32 per round-trip

DNS is allowed outbound by default in most enterprises; this is why it's the most resilient covert channel after HTTPS-with-domain-fronting. NDR / DNS-tier appliances catch it on volume + entropy, not on content.

## MITRE ATT&CK Tactics

- TA0011: Command and Control (T1071.004 DNS, T1572 Protocol Tunneling, T1568.002 Domain Generation Algorithms)

## XSIAM analytics rules triggered

| # | Rule | Stage |
|---|---|---|
| 5 | DGA-style High-Entropy DNS Queries | Stage 1 |
| 6 | DNS Tunneling (long subdomains, high volume) | Stage 2 |
| 7 | C2 Beaconing (periodic outbound) | Stage 3 |

## Data classes used

| Stage | Data class | If missing |
|---|---|---|
| 1, 2 | `dns` | Required — without DNS resolver telemetry, the entire skill is unobservable |
| 3 | `firewall` | Substitute with `dns` resolver outbound logs (lower fidelity) |

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

Call `data_sources_installed_as_vendors`. Group `vendors[]` by `data_source_class`. Verify `dns` is present — if missing, stop and tell the operator to install a DNS data source from the Marketplace before this skill can run. If the operator's DNS telemetry is installed via the firewall vendor (some PANOS deployments, for example), `dns` and `firewall` may resolve to the same vendor entry — that's fine; the same logs cover both stages.

## Narrative thread

- **Compromised host:** `wks-rdavies-01` at `10.10.20.55` (sales operations, `r.davies`)
- **Internal DNS resolver:** `10.10.0.53` (sees all internal queries, forwards external ones to `8.8.8.8`)
- **Attacker-controlled domain (Stage 1 probe pool):** `cdn-update-svc.tk`, `api-metrics-collector.cf`, `static-asset-cdn.ml`, `sync-telemetry-relay.gq`, plus 50 DGA noise siblings
- **Tunneling base domain (Stage 2 once one is selected):** `api-metrics-collector.cf`
- **Attacker NS (Stage 3):** `185.220.101.42` (Tor exit, threat-intel known-bad)
- **Wall-clock time:** Stage 1 ~10 min (50 queries spread out — the implant probes once every ~12s). Stage 2 ~25 min (continuous tunneling at 4-6 queries/sec). Stage 3 spans the full window as parallel firewall observation.

---

### Stage 1 — DGA probe pattern — ~50 queries over 10 minutes

The implant probes 50 algorithmically-generated subdomains looking for a NS that responds. 49 fail (NXDOMAIN); 1 succeeds (the attacker's actual registered domain).

**Data class:** `dns`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[dns].vendor>
  product: <stack[dns].product>
  count:    50
  interval: 12
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:       ["10.10.20.55"]
    shost:     ["wks-rdavies-01"]
    suser:         ["r.davies"]
    spt:     ["49152", "51234", "57890"]
    dpt:     ["53"]
    proto:     ["udp", "tcp"]
    query:        ["xkqp93jr9d2.cdn-update-svc.tk", "h3v8mz1t4q7.cdn-update-svc.tk",
                   "p4n2r9w8sx5.api-metrics-collector.cf", "z7t1y3v6m9k.static-asset-cdn.ml",
                   "j4l8q2n5r1m.sync-telemetry-relay.gq",
                   "v6h2k9m3p4q.cdn-update-svc.tk", "b7n5d3l8w2c.api-metrics-collector.cf",
                   "g8r4t1y6m9p.static-asset-cdn.ml", "f3w9k2j7d5h.sync-telemetry-relay.gq"]
    queryType:   ["A", "AAAA", "TXT"]
    responseCode: ["NXDOMAIN", "NXDOMAIN", "NOERROR"]
    responseIp:   ["", "0.0.0.0", "185.220.101.42"]
    ttl:           ["", "0", "30"]
    act:        ["allow"]
    cat:      ["uncategorized", "newly-registered-domain"]
```

**Field semantics:**
- `query` — the suspicious bit is the SUBDOMAIN structure: random alphanumeric strings that look algorithmically generated (DGA hallmark). The base domains are deliberately on `.tk`, `.cf`, `.ml`, `.gq` (free TLDs popular with adversaries)
- `query_length` — DGA queries are typically 25-40 chars; legitimate queries (CDN, mail, etc.) are usually shorter or follow predictable patterns
- `response_code` — most are `NXDOMAIN` (the DGA hasn't been registered); the few `NOERROR` ones are the attacker's live infrastructure
- `domain_age_days` — DGA C2 domains are very young (registered for this campaign)
- `category: newly-registered-domain` — modern DNS appliances enrich with domain age

**Why this fires Rule #5:** the entropy + length + young-domain + multi-variant probing pattern is the textbook DGA signature. Some SIEMs use ML-based entropy scoring; others use static rules ("≥10 distinct random-looking subdomains under same parent domain in <30 min").

---

### Stage 2 — DNS tunneling (long subdomains, high volume) — ~600 events over 25 minutes

Now that the attacker's DNS infrastructure is "live" (Stage 1 found the registered domain), the implant tunnels data through queries. Each query carries a chunk of base32-encoded payload (60+ chars in the subdomain). TXT responses carry the C2 commands back.

**Data class:** `dns`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[dns].vendor>
  product: <stack[dns].product>
  count:    600
  interval: 2
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:       ["10.10.20.55"]
    shost:     ["wks-rdavies-01"]
    suser:         ["r.davies"]
    spt:     ["49251", "51234", "60127"]
    dpt:     ["53"]
    proto:     ["udp", "tcp"]
    query:        ["MFRGGZDFMZTWQ2LK.NBSXSLTOMFXXG2DBNZSHE6JONRSWKMRRGEZTMNJWGY.api-metrics-collector.cf",
                   "ORSXG5BANBQXEIDFNRPGKZTBOJUW4YLOMVZHK4DBONUW63DPF52GS.api-metrics-collector.cf",
                   "JBSWY3DPEBLW64TMMQQGS5DEMVRWQ23MNEXG4Z3FNRSGS3ZPNRZA.api-metrics-collector.cf",
                   "MZXW6YTBOIAHC5DSEFQXG43JNYYHAYLGPBSWILDQOJTHE2LOM5ZA.api-metrics-collector.cf"]
    queryType:   ["TXT", "A"]
    responseCode: ["NOERROR"]
    responseIp:   ["185.220.101.42"]
    responseData: ["MFRGGZDFMZTWQ2LK", "ORSXG5BAONUW4ZTPONXW45DJ"]
    ttl:           ["30"]
    act:        ["allow"]
    dhost:        ["api-metrics-collector.cf"]
```

**Field semantics:**
- `query` — each is 80-110 chars. Subdomains in real queries are rarely >30 chars; the only legitimate use cases are DKIM selectors and some CDN edge servers, neither of which look like base32-encoded blobs
- `query_length` field — populating this lets the rule key on length directly rather than parsing
- `query_type: TXT` — the bulk of legitimate TXT queries are SPF/DKIM lookups against KNOWN domains; high TXT volume against a young uncategorized domain is anomalous
- `response_data` — TXT response payloads are also base32-encoded data going the other direction
- `domain: api-metrics-collector.cf` — same `.cf` domain across all queries (the chosen tunnel base, post-DGA-selection)

**Why this fires Rule #6:**
- Volume: 600 queries to one domain in 25 min from one host (typical legitimate volume to one external domain is <50/hr)
- Subdomain length: avg ~95 chars (legitimate queries avg ~20)
- TXT-record dominance for a non-mail-related domain
- Same source host, same target domain — high concentration
Combined, these cross multiple SIEM thresholds simultaneously.

---

### Stage 3 — Firewall confirmation of outbound DNS to attacker NS — ~120 events over 30 minutes

The firewall sees the outbound DNS traffic. Stage 1+2 produces resolver-tier logs; Stage 3 is the network-tier confirmation showing the firewall ALLOWED 600+ outbound DNS flows to the same external IP (the attacker's NS).

**Data class:** `firewall`

```yaml
xlog.create_data_worker:
  type:    CEF
  vendor:  <stack[firewall].vendor>
  product: <stack[firewall].product>
  count:    1
  interval: 15
  max_events: 120
  destination: logdest:<id from log_destinations_list>
  observables_dict:
    src:        ["10.10.0.53"]
    dst:        ["185.220.101.42"]
    dpt:      ["53"]
    proto:      ["udp", "tcp"]
    act:        ["allow"]
    app:           ["dns"]
    out:    ["120", "180", "240", "320"]
    in: ["180", "240", "320", "480"]
    country:       ["RU"]
    threatCategory: ["c2"]
    threatScore:    ["72"]
```

**Field semantics:**
- `src_ip: 10.10.0.53` — the internal DNS resolver, NOT the workstation. The workstation queries the resolver; the resolver forwards to external NS. So at the firewall, the source is the resolver
- `dst_ip` — the attacker's name server (matches Stage 2's `response_ip`)
- `dst_port: 53` over both UDP (most queries) and TCP (large TXT responses force fallback to TCP)
- `country: RU` — the destination country geo-enriches as RU; legitimate authoritative servers for `.cf` domains are typically in Frankfurt, Amsterdam — not Moscow
- `threat_category: c2` — modern firewalls' threat-intel feeds tag known-bad NS IPs with `c2` category

**Why this fires Rule #7:** the periodic outbound to the same external IP (every ~15s for 30 min) matches the beaconing definition. Some SIEMs use Fourier analysis to detect the periodicity; simpler ones key on connection-count + same-destination + threat-intel-match.

---

## Verification

| Indicator | Where to check |
|---|---|
| DGA / high-entropy DNS alert | XSIAM Issues |
| DNS tunneling alert against `api-metrics-collector.cf` | XSIAM Issues |
| C2 beaconing alert with destination `185.220.101.42` | XSIAM Issues |
| Pivotable: source host `10.10.20.55` correlates all 3 alerts | XQL: `config timeframe = 24h \| dataset = dns_logs \| filter src_host="wks-rdavies-01" \| limit 20` |

## Tear-down

```yaml
xlog.list_workers:
xlog.kill_worker:
  worker_id: <each>
```

## Adapting per deployment

The attacker IP `185.220.101.42` is illustrative. In a real exercise tied to a customer's threat-intel feed, replace it with an IP / domain pulled from the customer's TI program so the alerts also light up that integration's enrichment.
