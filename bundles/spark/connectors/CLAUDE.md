# `bundles/spark/connectors/` — per-instance connectors

Each connector ships as its own image, built at release time. The agent dispatches to per-instance containers via HTTP, not in-process Python — crash isolation + independent versioning. `phantom-updater` (see [`../../../updater/CLAUDE.md`](../../../updater/CLAUDE.md)) starts/stops the per-instance containers.

**Repo-wide rules live in the [root CLAUDE.md](../../../CLAUDE.md)** — credential guardrail, contained-release discipline, bug-family audit. This file holds only conventions LOCAL to connector authoring.

## Layout

Each connector is a subdirectory named after itself:
- `xlog/` — Phantom's log-generation tools (wraps the xlog service GraphQL)
- `xsiam/` — XSIAM PAPI integration
- `caldera/` — Caldera red-team operations
- `cortex-content/` — Cortex content catalog (data sources / packs / modeling rules) — local catalog at `cortex-content/baked/`
- `cortex-docs/` — Cortex documentation search
- `cortex-xdr/` — Cortex XDR API
- `web/` — Web browsing via Playwright + headless Chromium (phantom-browser CDP)
- `http-sender/` — sends synthetic JSON events to an XSIAM HTTP Log Collector or the Cortex Cribl endpoint. A bundle connector (shipped in the release image).
- `wec-sender/` — delivers synthetic Windows events to the Broker's Windows Event Collector over WS-Management. A bundle connector (shipped in the release image).


`connector.schema.json` (top-level here) is the JSON-Schema validator every `connector.yaml` validates against at boot AND at upload time.

## Connector authoring (the 5-step pattern)

1. **`connector.yaml`** — declares the connector's metadata, runtime style, schema, tool list, config fields. Validates against `connector.schema.json`.
2. **`src/connector.py`** — the connector's entry point. Inherits from the `phantom-connector-runtime` base (`../../../phantom-connector-runtime/`).
3. **`src/<tool>.py` files** — per-tool implementations.
4. **`tests/`** — connector-local pytest suite.
5. **`Dockerfile`** — `FROM ghcr.io/ayman-m/phantom-connector-runtime-oss:latest`. The release pipeline builds + tags each connector image at release time.

## Tool output shape

A tool's return payload carries **parsed fields only**. Never attach the unprocessed API response alongside fields already extracted from it.

The `xsiam`/`cortex-xdr` PAPI clients return the fully parsed JSON dict (`{"reply": {...}}`). Attaching that whole dict a second time as `raw_response` next to a slice of `resp["reply"]` would serialize the same bytes twice into every tool result, at agent-context cost, on every call.

The rule:
1. Extract what the tool's declared purpose needs, and return only that.
2. `raw_response` is permitted **only** on error paths, where it carries diagnostics no other field surfaces (e.g. `xsiam/src/connector.py`'s `xsiam_datamodel_describe` passing `raw_response=` to its error helper on a failed/timed-out poll — a keyword argument, not a duplicated dict key).
3. If a mutation endpoint's PAPI reply is a bare success marker, say so with an explicit field (`"updated": true`) — don't ship the raw ack to prove it. The connector's `@_wrap_xdr_call`/`@_xsiam_wrap` decorators already convert failures to `ok: false`, so reaching the success envelope *is* the proof.
4. If the parsed fields are genuinely incomplete for the tool's stated purpose, fix the extraction and declare the new field in `connector.yaml`'s `returns:` — don't paper over a gap with the raw dict.
5. `connector.yaml`'s `returns:` string is the contract. Code emitting a key the contract doesn't declare is a bug in one of the two — reconcile in the same change.

Grep for `"raw_response":` (the quoted dict-key form) across `src/connector.py` before merging a new tool or extending an existing one — a bare `raw_response=` keyword argument to an error helper is fine, a dict key isn't.

## Runtime style

`runtimeMapping.style: container` is the only supported style. Each instance = one Docker container, managed by `phantom-updater`. The agent's tool dispatcher proxies calls over MCP-over-HTTP to `http://phantom-connector-<id>-<name>:9000`.

## Catalog boundary

The agent has 4 MARKETPLACE tools available — these mutate catalog metadata:
- `marketplace_list` — read-only catalogue + install state
- `marketplace_install(connector_id)` — idempotent install row write
- `marketplace_uninstall(connector_id)` — refuses if any instances exist
- `connector_upload(yaml_content)` — validates + writes the user_connectors directory

The agent does NOT have INSTANCE tools — instances carry credentials, which are operator-only. See root § Catalog boundary ≠ credential boundary for the rule.

## Import-style discipline

Use `from src.X import Y` (with `src.` prefix) — NOT `from usecase.X import Y`. The latter only resolves with a specific PYTHONPATH that production deployments don't always have. Mixed import styles cause a family of bugs that only appear in the container. When in doubt, grep for `from usecase\\.` across connectors before merging.

## cortex-content / baked catalog

`cortex-content/baked/` ships **inside the agent image** — 197 packs / 232 schemas / 145 vendor logos / 576 files / 2.9 MB. Zero outbound network at runtime. The catalog is excluded from agent context via `.claudeignore` — to inspect it, hit `GET /api/v1/data-sources/catalog` on the running install or read the bake script at `scripts/refresh_cortex_baked_catalog.py`.

The refresh script is **maintainer-only** — never invoked at runtime, never referenced in operator-visible surfaces.

## User-uploaded connectors

The operator can upload custom `connector.yaml` via `POST /api/v1/marketplace/upload` (multipart) or `connector_upload(yaml_content)` (agent). Validation:
- Schema validation against `connector.schema.json` (same as bundle connectors).
- `id` must not collide with a bundle id (409 `id_collides_with_bundle`) or another user id (409 `id_already_exists`).
- YAML MUST declare an `image` field — the OCI reference to the operator's pre-published connector container. phantom-updater pulls this image when instances are created.

User connectors land at `/app/data/user_connectors/<id>/connector.yaml` (volume-persistent). They are first-class once they have an instance: tools register as `<id>.<tool>` (no legacy flat aliases), and the state routes and Tools panel resolve them. **Never read `manifest.yaml` directly to list connectors; use `usecase/connector_catalog.py`** (`effective_connectors()` / `find_connector()`), which returns bundle and uploaded connectors together. `DELETE /api/v1/marketplace/<id>` removes them. Bundle connectors are 403-rejected on DELETE — image-baked, can't be removed at runtime; use Uninstall to hide them from instance creation.
