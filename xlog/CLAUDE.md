# `xlog/` — log-generation backend

The `xlog` container. FastAPI + Strawberry GraphQL + the vendored first-party `app/logforge` generation engine. The single source of truth for log generation in Phantom — every faker / scenario / sender enum lives here, not in the MCP layer.

**Repo-wide rules live in the [root CLAUDE.md](../CLAUDE.md)**. This file holds only conventions LOCAL to xlog.

## Layout

| Path | What it is |
|------|------------|
| `main.py` | Mounts Strawberry GraphQL at `/` on the FastAPI app. |
| `app/schema.py` | All GraphQL queries + mutations. **Active workers live in a module-level `workers = {}` dict** — no persistence. Restarting the container drops every streaming worker; `listWorkers` is per-replica. |
| `app/types/datafaker.py` | Strawberry enums for worker types + faker formats. |
| `app/types/scenarios.py` | Scenario shape definitions. |
| `app/types/sender.py` | Destination + format enums. |
| `app/dynamic_schema.py` | Schema-override value generator for `generate_fake_data_v2`. Priority: `observable_overrides` → `type_hint` → field-name pattern → built-in generator fallback. |
| `app/config.py` | **The only** config surface: a `Config` class of `os.getenv` reads (`WORKERS_NUMBER`, `LOGGING_*`, `XSIAM_*`, `XLOG_API_KEY`). Env vars only — it does NOT read `config.yml`. New tunables go here. |
| `config.yml` | **Dead — reads nothing, affects nothing.** No module under `xlog/app/` imports yaml; its `workers: number: 25` stanza has no effect (the live value is `WORKERS_NUMBER` in `app/config.py`). It survives only because `scripts/export_agent_bundle.sh` copies it and the bundle manifest lists it. Do not add keys here expecting them to apply. |
| `scenarios/ready/*.json` | Pre-built scenario files. |
| `tests/` | pytest suite. |

## Single source of truth — log generation

The GraphQL endpoint is the **only** place log synthesis lives. The MCP server (`bundles/spark/mcp/`) calls it through the `xlog` connector (`bundles/spark/connectors/xlog/src/_graphql_client.py`). **Do not duplicate faker logic into the MCP layer or any connector.** If you find yourself reaching for `app.logforge` outside this directory, you're wrong.

## `app/logforge/` — the vendored generation engine

Log synthesis lives in **`app/logforge/`** and is **first-party code we own and maintain**. It has no external generation-library dependency. Format types, scenario shapes, and worker I/O are declared in `app/types/`.

| Module | Role |
|---|---|
| `rfaker.py` | `Events` + `Observables` — event synthesis per format, the observable field vocabulary (1169 fields) |
| `rsender.py` | `Sender` — the TCP/UDP/HTTP worker send loop |
| `rconverter.py` | format conversion between SYSLOG / CEF / LEEF / JSON |
| `constants/` | field vocabularies (attributes, sensors, sources, systems, db) |
| `schema/` | `supported_fields.json`, `required_presets.json` — loaded `__file__`-relative, so they travel with the package |

**Why in-repo:** owning the engine lets generation bugs be fixed directly in xlog, with no separate package release — as the `faker.unique` rule below requires.

**Import it as `from app.logforge import Events, Observables, Sender`.**

**`Faker` is a DIRECT dependency** (`requirements.txt`); the image needs it at import time.

### Never use `faker.unique` on a per-event path

`Events.faker` is a process-wide singleton and `faker.unique` maintains a ledger that is **never reset**. Generation runs once per event, so anything routed through `faker.unique` permanently consumes entries on every event and eventually raises `UniquenessException` for the rest of the process's life.

The failure mode is silent: a generator that burned ~10 names per event from a pool of ~1000 would cap xlog at **~100 events per container lifetime**, while workers still report `status=Running` and creates still return success. `_sample_distinct_names()` in `rfaker.py` avoids it by deduping locally within the returned list and touching no global state.

`tests/logforge_test_no_unique_leak.py` guards this. If you need distinctness, make it local and bounded; if you truly need process-global uniqueness, it does not belong on a per-event path.

### `count` means OPPOSITE things on the two sender paths

This is the single most important thing to know before creating a worker, and
getting it wrong is a ~200x volume error. The same GraphQL field, with the same
argument names, is interpreted two different ways depending on which sender
handles it:

| | legacy `Sender` (no `schema_override`) | `OverrideSender` (with `schema_override`) |
|---|---|---|
| loop | `while status == "Running" and count > 0` | `while not stop_event.is_set()` |
| `count` means | **total events** | **events per tick** |
| events per tick | always 1 | `count` |
| rate | `1 / interval` per sec | `count / interval` per sec |
| terminates on its own? | **yes**, after `count` events | **no**, runs until stopped |

So `count=200, interval=1` is:

- **200 events total**, finishing in ~200 seconds, on the legacy path
- **200 events per second — ~17 million/day, forever** — on the override path

Read as a total it looks trivially small, but it is a ~200x volume error:
misreading it can put ~720,000 events into a tenant in one hour.
That rate is only *reachable* on the override path: the legacy sender caps out
at 1 event per interval, so no value of `count` gets it near 200/sec.

The per-tick rule is not a general property of workers — it is true only of
`OverrideSender`.

Two safeguards apply on the override path:

- **Both paths log per event with the same phrasing.** `OverrideSender` and the
  legacy `Sender` both log "sending log message", so
  `docker logs xlog | grep -c "sending log message"` counts the traffic of both.
- **The implied rate is stated at creation.** `OverrideSender` logs its derived
  events/sec and per-day figure at startup, flagged `** HIGH RATE **` above
  10/sec, so a misread `count` surfaces immediately.

**`interval` must be >= 1 and is rejected below that.** The tick loop
throttles with `Event.wait(interval)`, and `Event.wait()` returns *immediately*
for both `0` and negative values — so a non-positive interval does not throttle
at all and spins as fast as the CPU allows. A negative interval also makes
`count / interval` negative, so the `per_sec > 10` high-rate check would pass
it silently — the most dangerous input would be the one that warned least.

When creating an override-path worker for sustained background telemetry,
prefer a small `count` over a long `interval` — `count=1, interval=5`
(0.2/sec) reads unambiguously, where `count=300, interval=1500` computes to
the same rate but invites the "300 events" misreading.

### Admission control — `app/worker_registry.py`

Every worker-creating resolver goes through `registry.admit(senders)`. It is
the ONLY path into the live-worker dict, which is what makes the ceilings
meaningful — there is no second door. Admission prunes, prices each sender,
checks the ceilings, mints a unique name, and inserts, all under one lock and
all-or-nothing. It never starts a thread, so a rejection cannot leave one
running.

| Ceiling | Env var | Default |
|---|---|---|
| Sustained per worker | `XLOG_MAX_WORKER_EVENTS_PER_SEC` | 10/sec |
| Declared burst | `XLOG_MAX_BURST_EVENTS_PER_SEC` | 500/sec |
| Burst total | `XLOG_MAX_BURST_EVENTS` | 50,000 |
| Concurrent bursts | `XLOG_MAX_CONCURRENT_BURSTS` | 1 |
| Aggregate sustained | `XLOG_MAX_TOTAL_EVENTS_PER_SEC` | 50/sec |
| Population | `WORKERS_NUMBER` | 25 |
| Per-worker event budget | `XLOG_WORKER_MAX_EVENTS` | 0 (off) |
| Per-worker lifetime | `XLOG_WORKER_MAX_LIFETIME_SECONDS` | 0 (off) |

`0` disables any ceiling. Lifetime bounds default OFF because Phantom
advertises *continuous* simulation — the rate ceilings already prevent floods.

**The ceiling is on the integral, not only the derivative.** A high rate is
refused as a *sustained* rate but granted as a *bounded burst* when the caller
declares `duration_seconds` or `max_events`. Generating telemetry at volume is
the product's purpose; a flat rate cap would break it.

**Bounded workers are priced by TOTAL, unbounded ones by RATE.** This is the
load-bearing asymmetry. A worker bounded by construction cannot run away — the
legacy `Sender` delivers exactly `count` events and stops, `WebhookSender`
walks a fixed payload list once — so capping its rate refuses harmless work
(a 100-event seeding run) while doing nothing for safety. An unbounded
worker's eventual volume is its rate times however long nobody notices, so
rate is the only thing worth capping there.

Boundedness is a property of the SENDER (`max_total_events`), never a claim by
the caller: `Sender` reports `count`, `WebhookSender` reports `len(payloads)`,
`OverrideSender` reports `None` unless `max_events`/`duration_seconds` was
declared — and those declarations are enforced in its tick loop, because the
higher ceiling was granted on that promise. Only a bounded run *faster* than
the sustained ceiling consumes a burst grant; otherwise `XLOG_MAX_CONCURRENT_
BURSTS=1` would serialize ordinary slow workers.

**Never price a worker from the request arguments.** Ask the sender via
`events_per_second(sender)` — `count` means opposite things on the two paths
(see the table above), so any formula over the GraphQL args is wrong by ~200x
for one of them. A sender class with no `events_per_second` property is priced
as *unbounded*: forgetting it fails closed, never silently uncapped.

## Webhook sender — non-Bearer auth header

The webhook sender uses header `Authorization: <WEBHOOK_KEY>` (RAW, not `Bearer`) — see `_get_webhook_headers` in `app/schema.py`. Any non-XSIAM webhook receiver must accept that form. **Never reformat this to `Authorization: Bearer <KEY>`** — it breaks every existing integration.

## Scenario file conventions

- Scenario files live in `scenarios/ready/*.json`.
- `createScenarioWorker` takes the filename **without `.json`** (e.g. `port_scan`, NOT `port_scan.json`).
- For inline scenarios use `createScenarioWorkerFromQuery` instead.

## Adding a new log format or destination

Touch BOTH:
1. The Strawberry enum in `app/types/datafaker.py` (worker type / faker format) or `app/types/sender.py` (destination).
2. The dispatch in `app/schema.py`.

If you only touch one, you'll ship an enum value that the dispatcher rejects, or a dispatch path that no client can reach. Both must change in the same commit.

## `generateFakeDataV2(requestInput, schemaOverride)`

The schema-aware GraphQL field for fake-data synthesis. When `schemaOverride` is supplied, top-level keys + value generation come from the override (vendor-faithful records). When omitted, it behaves identically to `generateFakeData`.

The override engine is in `app/dynamic_schema.py`. Each field's value resolves in priority order: `observable_overrides` → `type_hint` → field-name pattern (`srcip` → IPv4, `sentbyte` → byte-count integer) → built-in generator fallback.

## Tests

```bash
cd xlog
python3 -m pytest -x
```

## Pre-deploy gate

Pytest for xlog runs as part of the agent build (CI) — the agent image bakes the MCP, not the xlog service, but xlog tests are part of the workflow. Locally run xlog tests with the snippet above when touching `app/schema.py`, `app/types/*.py`, or `app/dynamic_schema.py`.
