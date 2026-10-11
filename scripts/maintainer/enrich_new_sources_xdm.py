#!/usr/bin/env python3
"""Onboard 5 new data sources to the validated XDM set.

FortiGate, SentinelOne, Microsoft Windows Events, Zscaler Internet Access
(cloud-NSS), Salesforce — all auto-migrated but never enriched. This
one-shot maintainer script makes each one map raw->XDM end-to-end via the
broker-CEF path (the validated-22 pattern, where the broker derives the
dataset as ``<lowercased-vendor>_<lowercased-product>_raw``).

Per source it:

  1. **Fixes routing** — sets ``vendor`` / ``product`` so the broker
     derives the correct ``<vendor>_<product>_raw`` dataset. 4 of 5 were
     wrong (Zscaler/Zscaler, Salesforce/Salesforce, Microsoft/
     MicrosoftWindowsEvents, Microsoft/SentinelOne).
  2. **Pins the gate-field example** to a value that clears the live
     XSIAM modeling-rule gate (the migrated placeholders — ``sample_channel``,
     ``authentication`` — fail their own gate).
  3. **Adds missing timestamp / gate fields** the parsing+modeling rules
     require but the connector schema lacked (Windows ``time_created``;
     Zscaler ``_raw_log.sourcetype`` + ``_raw_log.epochtime``).
  4. **Authors ``how_to_use``** — the broker-route boilerplate + a
     "### Make it map to XDM" section (gate seed + routing literal +
     timestamp + Verify XQL), matching the validated-22 template so the
     phantom agent generates correctly-mapping events unprompted.

It deliberately does NOT set ``validated: true`` — that pill + the
``validated_data_sources.txt`` membership are added in a follow-up commit
only after the end-to-end XDM run confirms each source on the deployed
install.

Round-trips each YAML via ``yaml.dump(sort_keys=False)`` (same as
``enrich_validated_yamls_v2.py``). Idempotent.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_SOURCES_ROOT = REPO_ROOT / "bundles" / "spark" / "data-sources"


# ─── how_to_use blocks (authored from live .xif + connector reads) ───

HTU_FORTIGATE = """\
## Sending these logs to Cortex XSIAM

Phantom emits FortiGate's wire format as CEF over UDP — point a data worker at
your XSIAM broker's syslog destination and these records flow straight in. The
CEF header's **vendor** + **product** drive XSIAM's parsing-rule routing: the
broker normalizes them to `<lowercased-vendor>_<lowercased-product>_raw`.

**Required CEF header for XSIAM**:

- **vendor**: `Fortinet`
- **product**: `FortiGate`

Broker derives → `fortinet_fortigate_raw`.

**MR pattern**: Flat CEF. The modeling rule reads FortiGate's proprietary
`FTNTFGT*` extension keys directly (`FTNTFGTlevel`, `FTNTFGTsubtype`,
`FTNTFGTpolicyname`, `FTNTFGTeventtime`, …) plus the standard CEF keys
(`src`, `dst`, `spt`, `dpt`, `act`, `proto`, `app`). Pack the vendor field
names as CEF extension `key=value` pairs.

**PR filter quirks**: `_time` is derived from `FTNTFGTeventtime` when present
(epoch nanoseconds; the rule strips the trailing 9 digits → epoch seconds). If
absent, the event still lands via the default route and `_time` falls back to
ingest time.

**Verify**:

```xql
datamodel dataset = fortinet_fortigate_raw
| filter xdm.observer.name contains "<your-marker>"
| fields xdm.*
| limit 1
```

### Make it map to XDM

The `fortinet_fortigate_raw` modeling rule is **unconditional** — it opens with
`alter` (no leading `filter`), so every event that lands in the dataset maps to
XDM. There is no gate field to seed. To get rich coverage, ensure the
`FTNTFGT*` extension keys carry realistic values (the modeling rule maps 25+
XDM fields from them: `xdm.source.ipv4`, `xdm.target.ipv4`,
`xdm.network.application_protocol`, `xdm.observer.action`, `xdm.network.rule`,
`xdm.event.outcome`, `xdm.source.user.username`, `xdm.target.user.username`,
`xdm.source.host.os_family`, and many more). Just stream — no `observables_dict`
gate seed required.
"""

HTU_S1 = """\
## Sending these logs to Cortex XSIAM

Phantom emits SentinelOne's wire format as CEF over UDP — point a data worker at
your XSIAM broker's syslog destination and these records flow straight in. The
CEF header's **vendor** + **product** drive XSIAM's parsing-rule routing: the
broker normalizes them to `<lowercased-vendor>_<lowercased-product>_raw`.

**Required CEF header for XSIAM**:

- **vendor**: `SentinelOne`
- **product**: `xdr`

Broker derives → `sentinelone_xdr_raw`.

**MR pattern**: Mixed flat + nested-JSON. The modeling rule branches on
`eventType` and reads both flat columns (`accountId`, `agentId`, `groupName`)
and nested JSON objects via `json_extract_scalar` (`agentDetectionInfo`,
`agentRealtimeInfo`, `threatInfo`, `alertInfo`, `sourceProcessInfo`). Pack the
nested objects as JSON-string CEF extensions.

**PR filter quirks**: `createdAt` (ISO-8601 with timezone, e.g.
`2026-05-26T14:23:01Z`) supplies `_time`.

**Verify**:

```xql
datamodel dataset = sentinelone_xdr_raw
| filter xdm.event.type != null
| fields xdm.*
| limit 1
```

### Make it map to XDM

The `sentinelone_xdr_raw` modeling rule only runs when `eventType` is one of
`"Activity"`, `"Threat"`, `"Alert"` — each is a separate mapping branch. When
simulating, pass `observables_dict={"eventType": "Threat"}` to
`phantom_create_data_worker` so the gate matches (Threat is richest — it maps
the MITRE technique + threat fields). The rule then populates core XDM:
`xdm.event.type` <- `eventType`, `xdm.alert.original_threat_id`/
`xdm.alert.original_threat_name` <- `threatInfo`, `xdm.source.host.hostname`/
`xdm.source.host.os_family` <- `agentRealtimeInfo`/`agentDetectionInfo`,
`xdm.source.process.*` <- `sourceProcessInfo`, and
`xdm.alert.mitre_techniques` from the indicators' tactic. Use `Activity` or
`Alert` to exercise the other branches.
"""

HTU_WINDOWS = """\
## Sending these logs to Cortex XSIAM

Phantom emits Windows Event Log records as CEF over UDP — point a data worker at
your XSIAM broker's syslog destination and these records flow straight in. The
CEF header's **vendor** + **product** drive XSIAM's parsing-rule routing: the
broker normalizes them to `<lowercased-vendor>_<lowercased-product>_raw`.

**Required CEF header for XSIAM**:

- **vendor**: `microsoft`
- **product**: `windows`

Broker derives → `microsoft_windows_raw`.

**MR pattern**: Flat + nested. The modeling rule reads `channel`,
`provider_name`, `event_id`, `message`, `user` (nested), and `event_data`
(nested object with per-event-id keys). Pack `event_data`/`user` as JSON-string
CEF extensions.

**PR filter quirks**: the ingest rule **requires** a `time_created` field
matching `HH:MM:SS` (e.g. `2026-05-26T14:23:01Z`) — without it the event is
dropped at ingest. It also **excludes** `provider_name` in (`Microsoft-Windows-
Sysmon`, `AD FS Auditing`, `Microsoft-Antimalware-Scan-Interface`,
`Microsoft-Windows-DNSServer`, `Microsoft-Windows-DNS-Server-Service`) — those
route to dedicated datasets.

**Verify**:

```xql
datamodel dataset = microsoft_windows_raw
| filter xdm.event.type = "System"
| fields xdm.*
| limit 1
```

### Make it map to XDM

The `microsoft_windows_raw` modeling rule only runs when `channel` is one of
`"System"`, `"Application"`, `"Directory Service"` **or** `provider_name` is a
recognized provider (`Microsoft-Windows-PowerShell`, `-TaskScheduler`,
`-Windows Firewall With Advanced Security`, `-Windows Defender`,
`-ActiveDirectory_DomainService`) **or** `provider_name` contains
`Microsoft-Windows-Security-`. Note **`"Security"` is NOT a valid `channel`** —
Security-audit events clear the gate through `provider_name` only. When
simulating, pass `observables_dict={"channel": "System"}` to
`phantom_create_data_worker` so the gate matches. The rule then populates core
XDM: `xdm.event.id` <- `event_id`, `xdm.event.type` <- `channel`,
`xdm.source.user.username`/`xdm.source.user.domain` from the `user` object,
`xdm.observer.type` <- `provider_name`, `xdm.event.description` <- `message`,
plus alert/auth fields for Defender/Security channels.
"""

HTU_ZSCALER = """\
## Sending these logs to Cortex XSIAM

Phantom emits Zscaler Internet Access cloud-NSS records as a JSON log line. This
is a **raw-log** source: the modeling rule reads the whole JSON object out of
`_raw_log` (`_raw_log -> sourcetype`, `_raw_log -> epochtime`, etc.), so the
vendor's fields must be packed **inside** the `_raw_log` JSON, not as top-level
columns.

**Required broker routing for XSIAM**:

- **vendor**: `zscaler`
- **product**: `cloudnss`

Broker derives → `zscaler_cloudnss_raw`.

> **Operator setup (raw-log source):** because the parsing rule reads
> `_raw_log`, this source needs a **Broker VM Syslog Applet** configured with
> vendor `zscaler` + product `cloudnss` on a dedicated source port. Without it,
> the JSON lands in `unknown_unknown_raw` and the modeling rule never fires.

**MR pattern**: Raw-log JSON. The parsing rule flattens `_raw_log` and the
modeling rule branches on `_raw_log -> sourcetype`.

**PR filter quirks**: `_time` is derived from `_raw_log -> epochtime`
(10-digit epoch seconds). Events without it still land (`no_hit=keep`) but get
ingest-time `_time`.

**Verify**:

```xql
datamodel dataset = zscaler_cloudnss_raw
| filter xdm.event.type = "zscalernss-web"
| fields xdm.*
| limit 1
```

### Make it map to XDM

The `zscaler_cloudnss_raw` modeling rule only runs when `_raw_log -> sourcetype`
is one of `"zscalernss-web"`, `"zscalernss-dns"`, `"zscalernss-fw"`,
`"zscalernss-audit"` — each is a separate feed-type mapping branch. The
connector's `_raw_log.sourcetype` field defaults to `zscalernss-web` (richest:
the web-proxy branch), so default generation clears the gate; to exercise
another branch pass `observables_dict={"_raw_log.sourcetype": "zscalernss-dns"}`.
The web branch populates core XDM: `xdm.event.type` <- `sourcetype`,
`xdm.network.http.url`/`xdm.network.http.url_category` <- the URL fields,
`xdm.source.ipv4`/`xdm.target.ipv4` <- client/server IPs,
`xdm.observer.action` <- `action`, `xdm.source.user.username` <- `user`, and
`xdm.event.outcome` from the request/response action.
"""

HTU_SALESFORCE = """\
## Sending these logs to Cortex XSIAM

Phantom emits Salesforce Real-Time Event Monitoring records as CEF over UDP —
point a data worker at your XSIAM broker's syslog destination and these records
flow straight in. The CEF header's **vendor** + **product** drive XSIAM's
parsing-rule routing: the broker normalizes them to
`<lowercased-vendor>_<lowercased-product>_raw`.

**Required CEF header for XSIAM**:

- **vendor**: `salesforce`
- **product**: `realtime`

Broker derives → `salesforce_realtime_raw`.

**MR pattern**: Flat columns. The modeling rule branches on `api_object_type`
and reads flat fields (`Username`, `SourceIp`, `LoginType`, `Status`,
`Platform`, `Browser`, `City`, `Country`, `EventDate`). Pack them as CEF
extension `key=value` pairs.

**PR filter quirks**: `EventDate` (ISO-8601 with timezone, e.g.
`2026-05-26T14:23:01Z`) supplies `_time`; the ingest rule filters on it.

**Verify**:

```xql
datamodel dataset = salesforce_realtime_raw
| filter xdm.event.type = "authentication"
| fields xdm.*
| limit 1
```

### Make it map to XDM

The `salesforce_realtime_raw` modeling rule only runs when `api_object_type`
matches one of its many Real-Time Event types — `"LoginEvent"`,
`"LoginAsEvent"`, `"ApiEvent"`, `"BulkApi"`, `"FileEvent"`,
`"CredentialStuffingEvent"`, `"ApiAnomalyEvent"`, `"ReportEventStream"`,
`"SessionHijackingEvent"`, … When simulating, pass
`observables_dict={"api_object_type": "LoginEvent"}` to
`phantom_create_data_worker` so the gate matches (LoginEvent is richest — it
maps the full authentication story). The rule then populates core XDM:
`xdm.event.type` = "authentication", `xdm.source.user.upn` <- `Username`,
`xdm.source.ipv4` <- `SourceIp`/`ForwardedForIp`, `xdm.event.outcome` <-
`Status`, `xdm.logon.type`/`xdm.event.operation_sub_type` <- `LoginType`,
`xdm.source.host.os`/`os_family` <- `Platform`, `xdm.source.location.city`/
`country` <- `City`/`Country`, and `xdm.target.url` <- `LoginUrl`.
"""


# ─── per-source fix config ───────────────────────────────────────

NEW: dict[str, dict[str, Any]] = {
    "FortiGate__FortiGate__fortinet_fortigate_raw": dict(
        vendor="Fortinet", product="FortiGate",
        gate=None,                       # unconditional
        add_fields=[],
        how_to_use=HTU_FORTIGATE,
    ),
    "SentinelOne__SentinelOneModelingRules__sentinelone_xdr_raw": dict(
        vendor="SentinelOne", product="xdr",
        gate=("eventType", "Threat"),
        add_fields=[],
        how_to_use=HTU_S1,
    ),
    "MicrosoftWindowsEvents__MicrosoftWindowsEvents__microsoft_windows_raw": dict(
        vendor="microsoft", product="windows",
        gate=("channel", "System"),
        add_fields=[
            dict(name="time_created", type="datetime",
                 example="2026-05-26T14:23:01Z",
                 description="Event creation time (ISO-8601). The ingest/parsing rule "
                             "filters on this field — it must contain HH:MM:SS or the "
                             "event is dropped at ingest."),
        ],
        how_to_use=HTU_WINDOWS,
    ),
    "Zscaler__ZscalerModelingRule__zscaler_cloudnss_raw": dict(
        vendor="zscaler", product="cloudnss",
        gate=None,                       # gate cleared via the added _raw_log.sourcetype example
        add_fields=[
            dict(name="_raw_log.sourcetype", type="string_short",
                 example="zscalernss-web",
                 description="NSS feed type. The modeling rule gates on "
                             "_raw_log -> sourcetype (zscalernss-web | -dns | -fw | -audit)."),
            dict(name="_raw_log.epochtime", type="integer",
                 example="1748263381",
                 description="Event time in epoch SECONDS (10 digits). The parsing rule "
                             "derives _time from _raw_log -> epochtime."),
        ],
        how_to_use=HTU_ZSCALER,
    ),
    "Salesforce__Salesforce__salesforce_realtime_raw": dict(
        vendor="salesforce", product="realtime",
        gate=("api_object_type", "LoginEvent"),
        add_fields=[],
        how_to_use=HTU_SALESFORCE,
    ),
}


def _apply(slug: str, cfg: dict[str, Any]) -> tuple[bool, str]:
    ypath = DATA_SOURCES_ROOT / slug / "data_source.yaml"
    if not ypath.is_file():
        return (False, "MISSING")
    doc = yaml.safe_load(ypath.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        return (False, "not a dict")

    notes: list[str] = []

    # 1. routing
    if doc.get("vendor") != cfg["vendor"]:
        notes.append(f"vendor {doc.get('vendor')!r}->{cfg['vendor']!r}")
        doc["vendor"] = cfg["vendor"]
    if doc.get("product") != cfg["product"]:
        notes.append(f"product {doc.get('product')!r}->{cfg['product']!r}")
        doc["product"] = cfg["product"]

    fields = doc.setdefault("fields", [])
    by_name = {f.get("name"): f for f in fields if isinstance(f, dict)}

    # 2. gate-field example
    if cfg["gate"]:
        gf, gv = cfg["gate"]
        f = by_name.get(gf)
        if f is None:
            return (False, f"gate field {gf!r} ABSENT — cannot pin")
        if f.get("example") != gv:
            notes.append(f"gate {gf}.example {f.get('example')!r}->{gv!r}")
            f["example"] = gv

    # 3. add missing fields
    for nf in cfg["add_fields"]:
        if nf["name"] in by_name:
            ex = nf.get("example")
            if by_name[nf["name"]].get("example") != ex:
                by_name[nf["name"]]["example"] = ex
                notes.append(f"set {nf['name']}.example={ex!r}")
        else:
            fields.append(dict(nf))
            notes.append(f"+field {nf['name']}")

    # 4. how_to_use
    if doc.get("how_to_use", "") != cfg["how_to_use"]:
        notes.append(f"how_to_use ({len(cfg['how_to_use'])} chars)")
        doc["how_to_use"] = cfg["how_to_use"]

    if not notes:
        return (False, "no change")

    new_yaml = yaml.dump(doc, sort_keys=False, allow_unicode=True,
                         width=100, default_flow_style=False)
    ypath.write_text(new_yaml, encoding="utf-8")
    return (True, "; ".join(notes))


def main() -> int:
    print(f"# Onboard {len(NEW)} new data sources to XDM\n")
    changed = 0
    for slug, cfg in NEW.items():
        ok, reason = _apply(slug, cfg)
        marker = "✓" if ok else ("✗" if reason not in ("no change",) else "·")
        print(f"  {marker} {slug}\n      {reason}")
        if ok:
            changed += 1
        elif reason not in ("no change",):
            print(f"  !! ABORT on {slug}: {reason}", file=sys.stderr)
            return 1
    print(f"\n# Done. {changed}/{len(NEW)} updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
