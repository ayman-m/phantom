---
name: trigger_network_analytics_alerts
displayName: Trigger network-traffic Analytics/BIOC alerts (port scan, spam bot, lateral movement)
category: workflows
description: 'Generate firewall telemetry (PAN NGFW, FortiGate) shaped to deliberately fire Cortex XSIAM''s network-traffic Analytics detectors and BIOC rules — Suspicious Port Scan (vertical/horizontal/distributed variants), Spam Bot Traffic, Suspicious SMB Connection From Domain Controller — rather than just landing raw/modeled rows. Use when the operator wants a demo alert to fire, wants to prove network detections work end-to-end on a proof-of-value tenant, or asks "how do we trigger a port scan / spam bot / lateral movement alert". Encodes the exact event shapes: how many distinct ports/destinations, what time window, which fields are load-bearing, and — critically — which of these detectors re-fire on repeat traffic versus which are rarity-gated per source entity and need a fresh target to fire again.'
icon: security
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Trigger network-traffic Analytics/BIOC alerts

## When this skill applies

The operator wants a **network-traffic detector to actually fire**, not just clean `xdm.*`
mapping. Distinguish this from `stream_simulate_to_xsiam` (lands + verifies XDM) and
`data-source-xdm-validation` (reverse-engineers a modeling rule) — this skill is one layer
further down the pipe: **stage ④ of the signal path** (see `cortex-signal-path`), where an
already-modeled feed needs to clear a detector's own shape/volume/rarity gate.

Matches:
- *"Trigger a port scan alert."* / *"Make the suspicious port scan detector fire."*
- *"I need a spam bot alert for the demo."*
- *"Show lateral movement / PetitPotam-style detection."*
- *"We got a random alert — how do we reproduce that on demand?"*

Route elsewhere when the ask is generic volume with no specific detector in mind
(`stream_simulate_to_xsiam`), or the feed isn't modeling at all yet (`data-source-xdm-validation`).

---

## The one thing that matters more than the event shape: does this detector re-fire?

These three detectors can be triggered with isolated one-shot bursts.
**They do not behave the same way on repeat traffic**, and that difference is the single most expensive thing to not know going into a
live demo:

| Detector | Class | Re-fires on repeat traffic? |
|---|---|---|
| Suspicious Port Scan | `XDR_ANALYTICS` (volumetric/shape) | **Yes**, from a different source host each time. The alert arrives 3.5-12 minutes after the burst, and the same host is deduplicated for 1 day. **Use `trigger_port_scan_analytics`**, which has the exact tool call |
| Spam Bot Traffic | `XDR_ANALYTICS` (volumetric, rolling window) | **Fires eventually, but NOT from a single instantaneous FortiGate burst** — a well-shaped one-shot burst (27 distinct SMTP destinations, well over the ~15 threshold) raises no alert within ~9 minutes of observation. This detector appears to run on a slower evaluation cadence than Port Scan; do not rely on it firing live in front of an audience (for Palo Alto traffic use `trigger_spam_bot_alert`) |
| Suspicious SMB Connection From Domain Controller | `XDR_ANALYTICS_BIOC` (behavioral indicator) | **Not within 7 days**: the Cortex doc gives this rule a **7-day deduplication period** per source. That is why an identical pattern does not fire again 28 hours later. The DC role comes from the tenant's own asset classification of a real domain controller (the alert is attached to the real DC agent and tagged `R:Domain Controllers`), not from a host name. A synthetic host merely *named* `DC02` is not a domain controller to the detector |

**Practical rule: for a repeatable, watch-it-happen demo, use Suspicious Port Scan only.** It is
the only one of the three that fires fast and repeatedly (use a new source host each time). The
other two are effectively **one-shot, slow, or both** — pre-stage them well before a meeting
(fire the burst, then wait — possibly tens of minutes to hours) rather than trying to trigger
either live. Neither Spam Bot Traffic (FortiGate feed) nor the SMB BIOC raises a second alert within ~10
minutes of watching, even when the underlying traffic shape is correct.

---

## Suspicious Port Scan: moved to `trigger_port_scan_analytics`

The port-scan recipe now has its own skill, **`trigger_port_scan_analytics`**. It gives the verbatim
`phantom_create_data_worker` arguments, the landing check, the alert check with a 15-minute wait
budget, and the expected result. Load that skill; do not
rebuild the recipe from memory.

The corrections it carries, summarised:

- The routing literal is `panw`/`ngfw_traffic`, not `Palo Alto Networks`/`NGFW Traffic`.
- The bounds are `duration_seconds`/`max_events`. `durationSeconds`/`maxEvents` are not this tool's
  arguments.
- The count that matters is distinct ports to **one** target. 18 is the lowest count known to fire.
- Alerts arrive 3.5-12 minutes after the burst, not about 1 minute.

**Field-subset warning (applies to every recipe in this skill, not just port scan).** Send a
NARROW field subset via `schema_override`, not the vendor's full schema. Two things go wrong
otherwise: the broker truncates syslog past ~4 KB, and every field left unpinned gets a random
value — which the modeling rule may then prefer over the one you deliberately pinned. Concretely
on FortiGate: `xdm.source.ipv4` coalesces across eleven candidate columns (`src`,
`sourceTranslatedAddress`, `FTNTFGTnat`, `FTNTFGTsaddr`, `FTNTFGTbanned_src`, `c6a2`, …) — ship
the full schema unpinned and the rule may resolve the scan source from a random one of those
instead of the field you actually set, giving every event a different "attacker" IP and
destroying the scan pattern entirely (for example 20 events landing as 20 distinct source IPs
raise zero detections). Keep `schema_override` to the handful of fields the recipe actually needs.

---

## Spam Bot Traffic

> **For Palo Alto traffic, use `trigger_spam_bot_alert`.** One bounded burst of 24 `smtp`/25 events to 24 public addresses from a Palo Alto NGFW traffic source raises the alert about **4 minutes** after the first tick, including from a host with no earlier traffic. The FortiGate attempts below do not fire inside their observation window; the warning that follows ("not a fast shape detector") applies to the FortiGate feed and does not hold for the Palo Alto feed.

**Source**: FortiGate (`fortinet_fortigate_raw`, vendor/product `Fortinet`/`FortiGate`, CEF).

**Alert shape** (a host such as `WS-2111`; alert text: *"connected to 15 SMTP servers in
the last 3 days"*):

- ONE internal source host
- **15+ distinct external destination IPs**, `dest_port` 25 or 587, `app = SMTP`, `proto = 6`
- Destination hostnames can be plausible mail-relay names (`mail-outNN.bulk-relay-N.info`) or
  reused generic hosts — the detector reads the IP/port/app shape, not the hostname string

**Take the "last 3 days" language seriously — this is NOT a fast shape detector like Port Scan.**
Two verification bursts show the behaviour:

- 20 events across a 20-IP pool with random sampling land only about **11 distinct**
  destinations (under the ~15 threshold) — no alert, because the shape itself is under-strength.
- 50 events across a 35-IP pool land about **27 distinct** destinations, comfortably clearing the
  threshold. Polled every 20s for ~9 minutes: **still no alert.**

**Conclusion: unlike Port Scan, a correctly-shaped single-tick burst is not sufficient on its own
to fire this detector inside a short observation window.** Either it runs on a materially slower
evaluation cadence than the BIOC/analytics-shape detectors, or it wants the distinct-destination
count to build up with some minimum spread in `_time` (not literally 3 real days). When this needs
re-arming, try events explicitly back-dated across a few hours rather than all in one tick. **Do not plan a live demo around triggering this one on the spot.**
Fire the burst well ahead of time and treat the alert landing as a bonus, not a guarantee.

**Fields that mattered**: `src`, `dst`, `spt`, `dpt`, `shost`, `dhost`, `app`, `proto`.

**Re-arming for a future attempt**: use a **new `shost`** each time (the alert does not repeat
from the same host while its traffic continues, so it is at least per-source-entity rather than
per-tenant-volume) — but budget real
time, not just a single well-shaped tick.

**Recipe**:

```
type: CEF
vendor: Fortinet
product: FortiGate
count: 50            # oversample — a pool this size with random sampling still loses ~1/3 to collisions
interval: 1
duration_seconds: 60
max_events: 50
schema_override.fields: [src, dst, spt, dpt, shost, dhost, app, proto]
observables_dict:
  shost: ["<fresh-hostname-not-used-before>"]
  src: ["<internal-ip>"]
  dpt: ["25", "587"]
  app: ["SMTP"]
  proto: ["6"]
  dst: [<30-35 distinct external IPs — see the oversampling note below>]
```

**Oversampling note**: `observables_dict` list values are sampled per-event, WITH replacement. A
pool of N distinct values drawn M times lands roughly `N * (1 - ((N-1)/N)^M)` distinct values, not
M. To land ~20+ distinct destinations reliably, use a pool of 30-35 IPs with `count=50`, and
confirm the actual landed distinct count before concluding a test is negative:
`dataset = fortinet_fortigate_raw | filter shost = "<your-shost>" | comp count_distinct(dst) as n`.
This applies to every recipe in this skill, not just Spam Bot Traffic — undersampling is a common
cause of a false negative.

**Verify**: `dataset = alerts | filter alert_name = "Spam Bot Traffic" | sort desc _time | limit
5`. Budget real wall-clock time (a correctly-shaped FortiGate burst can stay silent for ~9
minutes) — do not conclude failure quickly.

---

## Suspicious SMB Connection From Domain Controller (lateral-movement BIOC)

**Source**: confirmed reachable from BOTH `panw_ngfw_traffic_raw` and `fortinet_fortigate_raw` —
the underlying traffic pattern (a domain controller initiating SMB, port 445, to
one or more workstations — the PetitPotam/PrinterBug-suspicious reversed direction) is shown
on FortiGate.

**Shape**: source host is a domain controller identity (`shost`/`source_device_host` = a DC-named
host, e.g. `DC01`), `dest_port = 445`, `app = SMB`, destination is a workstation-shaped host, not
another server.

**This is the one to plan around carefully.** It is a BIOC (deterministic pattern rule, not a
baselined ML detector), so in principle it should fire every time the pattern is observed — but
in practice it does not:

- A first burst: DC01 -> 4-5 workstation-shaped hosts over SMB, 80 events in 38s. The alert
  fires within ~4 seconds of the burst landing.
- A second burst, same DC01, same 4-5 destination hosts, ~28 hours later: 40 events in 195s,
  textually identical pattern. **No alert.**
- An isolated burst from DC01 to two brand-new, never-before-seen destination hostnames
  (`WS-VERIFY-01`/`-02`, fresh IPs, landed and confirmed in the raw dataset), polled every 20s
  for a full 7 minutes (20 checks): **no alert.**

**Conclusion**: the rule is rarity-gated **on the source entity** (has this DC already
been flagged for this behavior recently), NOT on destination novelty — a genuinely fresh
destination is not sufficient to re-arm it. Treat this detector as
effectively **one alert per source-DC identity per some longer cooldown window** (unconfirmed
exact duration, but > 28 hours and apparently not reset by a new target within the same session).
For a repeatable demo, use a **different DC-named source host** each time
(`DC01`, `DC02`, `DC-EU01`, ...) rather than trying to re-trigger from the same one.

**Fields that mattered**: `src`, `dst`, `shost`/`source_device_host`, `dhost`/`dest_device_host`,
`dpt`/`dest_port` (`445`), `app` (`SMB`/`smb`), `proto`/`protocol` (`6`/`tcp`).

**Recipe**:

```
type: CEF
vendor: Fortinet
product: FortiGate
count: 40-80
interval: 1
duration_seconds: 60
max_events: 80
schema_override.fields: [src, dst, spt, dpt, shost, dhost, app, proto]
observables_dict:
  shost: ["<never-used-DC-hostname>"]
  src: ["<DC-ip>"]
  dpt: ["445"]
  app: ["SMB"]
  proto: ["6"]
  dhost: [<one or more brand-new workstation-shaped hostnames>]
  dst: [<matching brand-new internal IPs>]
```

**Verify**: `dataset = alerts | filter alert_name = "Suspicious SMB connection from domain
controller" | sort desc _time | limit 5`. Give it at least 5-10 minutes before concluding a burst
did not fire — this rule is not as fast as the port-scan detector.

---

## Shared mechanics (all three)

- All three detectors are `XDR_ANALYTICS` or `XDR_ANALYTICS_BIOC` — **not** `CORRELATION`,
  `POSTURE_POLICY`, `HEALTH`, or `CUSTOM_ALERT`. When checking, always exclude those four sources
  or the signal drowns in noise:
  ```
  dataset = alerts | filter alert_source != "CORRELATION" and alert_source != "POSTURE_POLICY"
    and alert_source != "HEALTH" and alert_source != "CUSTOM_ALERT" | sort desc _time
  ```
- All three are driven off flat CEF extension keys on the vendor's native traffic dataset — no
  JSON composites, no rule reverse-engineering needed. The hard part is the detector-level gate
  (volume, rarity), not the modeling-rule mapping.
- One-shot verification bursts should always set `duration_seconds`/`max_events` so the worker
  self-terminates — these are point-in-time triggers, not long-running traffic. Firing
  them as `OverrideSender` workers with no cap risks the same self-defeat / population-cap
  problems as any uncapped long-running worker.
- Respect the 25-worker population cap (`WORKERS_NUMBER`). A one-shot verification burst is cheap
  (30-60s to self-terminate) but still counts against the cap while running.

## What this does NOT cover

Other detector families that remain out of reach with this approach (Failed Connections,
Large Upload, Rare LDAP enumeration, Torrent, FTP, Rare AppID, Uncommon SSH) are out of scope
here — this skill documents only the three network-traffic detectors above. Extend
this file with new sections as more are reverse-engineered, following the same "shape + re-fire
behavior + recipe + verify query" structure.
