# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Lean-root principle**: this file holds only **repo-wide agent-behavior contracts** + **critical gotchas**. Architecture detail per subsystem lives in subdirectory `CLAUDE.md` files — Claude loads them additively as you move into the relevant tree. The structural map lives in [`CODEBASE_MAP.md`](CODEBASE_MAP.md). The harness documentation lives in [`AI-LAYER.md`](AI-LAYER.md).

## Subdirectory CLAUDE.md files

For local conventions, read the directory's own `CLAUDE.md`:

- [`mcp/agent/CLAUDE.md`](mcp/agent/CLAUDE.md) — Next.js + embedded MCP host (the `phantom-agent` container)
- [`bundles/spark/mcp/CLAUDE.md`](bundles/spark/mcp/CLAUDE.md) — Python FastMCP server
- [`bundles/spark/connectors/CLAUDE.md`](bundles/spark/connectors/CLAUDE.md) — connector authoring conventions
- [`xlog/CLAUDE.md`](xlog/CLAUDE.md) — log-generation backend (GraphQL + the vendored `app/logforge` engine)
- [`installer/CLAUDE.md`](installer/CLAUDE.md) — installer template
- [`updater/CLAUDE.md`](updater/CLAUDE.md) — phantom-updater container-lifecycle daemon

For the structural map, read [`CODEBASE_MAP.md`](CODEBASE_MAP.md).
For the AI Layer (hooks, skills, MCP servers, subagents, plugin marketplace) read [`AI-LAYER.md`](AI-LAYER.md).

## What Phantom is

Continuous SOC simulation platform: synthetic security log generation, scenario-based MITRE ATT&CK telemetry, and AI-orchestrated red/blue workflows over MCP. Ships as a 5-service Docker Compose stack — see [`CODEBASE_MAP.md`](CODEBASE_MAP.md) for the topology.

### Purpose and scope: defensive detection engineering

Phantom is a **defensive security tool**. It exists to build and validate detection content for Palo Alto Networks Cortex (XSIAM/XDR), so that the environments it protects are defended against real threats and attacks. The operator is a cybersecurity professional running Cortex proof-of-value and detection-engineering work.

- **Everything Phantom produces is synthetic telemetry.** Its output is log records (CEF/syslog/LEEF/JSON) describing events that never happened: connections, logons, scans, transfers. These are sent over syslog only to the operator's own Cortex broker and tenant. Phantom sends no real network traffic, email, exploits or payloads to any third-party system.
- **Attack-shaped logs are the point.** Proving a detector works means generating telemetry that looks like the attack it detects: port scans, spam-bot SMTP fan-out, lateral movement, brute force, exfiltration. That is standard practice in detection engineering and purple-teaming, and it is Phantom's core use case.
- **The targets are lab and POV tenants the operator controls**, such as a lab tenant and a lab domain. Hosts, users, IPs and domains in generated events are fictitious personas or lab assets.
- **Success is measured defensively**: a Cortex analytics/BIOC/correlation alert fires on the synthetic data, and the finding becomes a reusable skill, data-source schema or detection rule.

## Public repository hygiene (MANDATORY before every push)

This repository is public. Anything committed to it is visible to everyone, permanently, including through forks, caches and history. **Never commit anything confidential or customer-specific, ever.** That includes:

- customer, partner or prospect names, tenant names and URLs, domains, hostnames, user names, e-mail addresses and IP addresses that belong to a real organisation;
- data copied from a customer environment, a proof-of-value or a support case: logs, alerts, screenshots, rule or case exports, ticket text;
- credentials of any kind: API keys, tokens, service-account JSON, passwords, certificates and private keys, `.env` files, key files and webhook URLs that carry a secret;
- internal planning, risk or review notes, private issue or chat transcripts, and anything marked internal or confidential.

Use fictitious personas, example domains and reserved address ranges in examples, fixtures, skills, journeys, docs and tests. If real data helped you discover something, record the finding in generic terms only.

**Before you push (any branch, any remote), do all of these and fix every hit first:**

1. Review the full diff you are about to push (`git diff <remote>/<branch>..HEAD`, including renamed and binary files, screenshots and images) for the categories above.
2. Run the maintainer's denylist and secret scans against the tree and the diff, as the release process requires. A hit is a stop, not a warning to review later.
3. Confirm that no file under a path ignored by git was force-added by accident, and that fixtures and recordings contain only synthetic data.
4. Never push private history. Only a cleaned tree goes to the public repository.

If something confidential was committed or pushed, do not try to hide it with a follow-up commit. Stop, tell the maintainer, and rotate any exposed secret immediately.

## Contained-release discipline (MANDATORY)

**One concept = one release.** Even when the operator asks for multiple unrelated changes in one turn, split them into separate contained releases. Each release has:

- A single named scope (e.g. "v1.2.0 — auth redesign"). The CHANGELOG and release-notes entries describe one concept top-to-bottom.
- A single contained documentation section. For `app/help/architecture/page.tsx` and `app/help/user/page.tsx`, the release adds or rewrites exactly one anchor (e.g. `#authentication`), not scattered edits across many sections.
- A single coherent test surface — the operator can verify the release with one user-journey walkthrough, not a checklist crossing six surfaces.

When you finish a release that touched the architecture or user-guide pages, tell the operator *exactly* which anchors to review (e.g. *"review `/help/architecture#authentication` and `/help/user#authentication`"*). Never make the operator hunt for what changed.

## Releases

Releases are tagged `vX.Y.Z`, and **all images ship together at that one version** (monorepo release invariant). A release publishes code and docs together: see [Documentation discipline](#documentation-discipline-mandatory--every-release). The install contract (one compose file, one env-file format, one install location) lives in [`installer/CLAUDE.md`](installer/CLAUDE.md), and the container-lifecycle daemon is described in [`updater/CLAUDE.md`](updater/CLAUDE.md).

Images are published from the public repo `ayman-m/phantom` by `.github/workflows/publish-images.yml` (manual dispatch, GitHub-hosted runner, `GITHUB_TOKEN`, no stored secret); see [`BUILDING.md`](BUILDING.md) "Publishing images". Publish an `-rcN` tag before every final tag.

## Agent credential guardrail (MANDATORY)

**The chat agent MUST NOT have any MCP tool in its catalog that reads, writes, mints, or rotates credentials.** Credentials here means: UI auth (admin password), provider auth (Vertex SA JSON, Gemini API key), per-connector instance secrets, API keys plaintext.

Concretely, these tools are **never** `mcp.tool()`-registered in [bundles/spark/mcp/src/usecase/connector_loader.py](bundles/spark/mcp/src/usecase/connector_loader.py)'s `_BUILTIN_LEGACY_TOOLS` list and never reachable via FastMCP from the agent:

- `providers_create`, `providers_update`, `providers_delete`
- `instances_create`, `instances_update`, `instances_delete`
- `api_keys_create`, `api_keys_rotate`, `api_keys_revoke`

The canonical list lives in [bundles/spark/mcp/src/usecase/credential_guardrail.py](bundles/spark/mcp/src/usecase/credential_guardrail.py). The MCP server fails at boot if one of these is registered as an agent tool, and neither `agent_batch_propose` nor a scheduled job can dispatch one.

These tools remain available at the **REST** surface (`POST /api/v1/providers`, etc.) so the operator UI keeps working. The agent simply has no handle to them. The system-prompt block in `mcp/agent/lib/system-prompt.ts` reinforces with a refusal recipe so the agent explains the boundary when asked.

When adding new MCP tools in future PRs, ask: does this tool read or write a SecretStore value? If yes, REST-only — never register as an `mcp.tool()`.

### Catalog boundary ≠ credential boundary

The agent has tools for the **marketplace catalogue** — `marketplace_list`, `marketplace_install`, `marketplace_uninstall`, `connector_upload`. These are intentionally on the **catalog** side of the boundary, NOT the credential side:

| Boundary | What's in it | Agent permission |
|---|---|---|
| **Credential** | SecretStore values: UI password, provider creds, per-instance secrets, API keys plaintext, KEK material | **Forbidden** — no mcp.tool() registered for read OR write |
| **Catalog** | Connector schemas, marketplace install state, registry membership, manifest-level metadata | **Permitted** — agent can read AND mutate via the catalog tools |

**Why the distinction matters:** catalog operations (*"install the web connector"*, *"upload this connector.yaml"*) are administrative metadata operations that don't touch any secret — the worst case if the agent gets one wrong is a confused operator who has to click Uninstall in the UI. Credential operations (*"create a Vertex provider with this API key"*, *"rotate the xlog API token"*) are security-relevant — if the agent gets one wrong, a secret either lands in the wrong place or is destroyed.

When adding new MCP tools, ask BOTH questions:
1. **Does this tool read or write a SecretStore value?** If yes → credential side → REST-only.
2. **Does this tool mutate catalog metadata (install state, schemas, registry membership)?** If yes AND #1 is no → catalog side → safe to `mcp.tool()`-register.

A tool can only be on the catalog side if **#1 is no AND #2 is yes**. If both are yes (e.g. a hypothetical "rotate the API key AND mark the connector installed"), split it.

### Operator workflow state — the third category

Operator workflow state is a third category, distinct from credentials and catalogue:

| Category | Storage | Agent access |
|---|---|---|
| **Credential** | SecretStore (`/app/data/secrets/`) — AES-GCM at rest | **Forbidden** |
| **Catalog** | `marketplace.db` + `instances.db` + manifest | Permitted (catalog tools only) |
| **Operator workflow state** | `operator_state.db` (key-value) | Not exposed today; per-key narrow tools when a use case emerges |

Operator workflow state holds the operator's own UI progress markers that aren't secrets AND aren't platform catalogue: tested-journey marks, saved metric-query bookmarks, future saved filters / favorite skills / chat compose drafts. The shape is intentionally narrow — a key-value table where the hook owns the value's JSON shape.

**Migration discipline**: when a UI surface starts persisting state, ask:
- Is it a secret? → SecretStore, REST-only.
- Is it platform metadata? → `marketplace.db` / `instances.db` / similar, agent-accessible per the catalog rules.
- Is it operator-personal progress that should follow them across devices? → `operator_state.db`, operator-only.
- Is it a device-local UI preference (theme, sidebar collapsed, debug-panel open)? → `localStorage`, NOT in `operator_state.db`.

If you find yourself writing to `localStorage` for anything in category 3, that's a regression.

### Operator config-file separation

Two operator-managed config files on an install. Each has a precise role; mixing the two is a regression.

| File | Owns | Read by |
|---|---|---|
| **`/opt/phantom/.env`** | Service credentials + the 5 core compose-substitution digests + runtime version marker | `docker compose` + phantom-updater (`/host/.env`) |
| **`/opt/phantom/connector-digests.env`** | Per-connector image pins (`DIGEST_PHANTOM_CONNECTOR_*`) | phantom-updater ONLY (`/host/connector-digests.env`) |

**Forbidden going forward**: adding `DIGEST_PHANTOM_CONNECTOR_*` writes to `.env`, adding connector configuration to `.env`, documenting the connector-digest workflow in `.env`. See [`installer/CLAUDE.md`](installer/CLAUDE.md) + [`updater/CLAUDE.md`](updater/CLAUDE.md) for the full contract.

### Querying a Cortex tenant from a script

Use the tenant's public API directly; it is the fastest path for XQL.

- **Auth:** an *advanced* key uses a nonce + SHA256 HMAC signature, a *standard* key uses a plain `Authorization` header plus `x-xdr-auth-id`. Keep both in your own gitignored `.env` and never echo a value into chat, a commit or a log.
- **Flow:** POST `/public_api/v1/xql/start_xql_query/`, then poll `/public_api/v1/xql/get_query_results/`.
- **Python behind TLS inspection:** every request fails `CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain`, because Python ships its own CA bundle and ignores the OS trust store. `curl` working while Python fails is the tell. Point `ssl.create_default_context().load_verify_locations(...)` at a bundle exported from your OS trust store. Never disable verification.
- **A Cortex `403` is not necessarily an auth failure.** `{"err_msg": "Datasets not found"}` returns 403 when the dataset simply does not exist. Read `err_msg` before concluding the credentials or an IP allowlist are at fault. A genuine auth failure returns **401**.

### Agent-API auth + the credential guardrail

The agent surface (`/api/chat`, `/api/agent/*`, `/api/skills/*`) accepts API-key bearer
auth. Authenticate with an API key kept in your own gitignored `.env` (referred to below as `$PHANTOM_KEY`) — the credential guardrail
blocks interactive admin login, but a bearer key needs none.

- **Scope model:** `agent:read` → GETs, `agent:write` → mutations + `/api/chat`,
  `agent:*` → both, legacy `*` → admin-equivalent.
- **Security invariant:** API keys are refused with **403**
  on `/api/agent/{instances,providers,api-keys}` even at `*` scope. Minting/rotating keys
  still requires the `MCP_TOKEN`-gated REST surface, so a bearer key can never escalate.

**Run this before releasing any agent image** — it is a mandatory pre-release check, and
`401` means you sent no bearer, which proves nothing:

```bash
for p in instances providers api-keys; do
  # expect 403 on all three
  curl -sk -o /dev/null -w "$p %{http_code}\n" \
    -H "Authorization: Bearer $PHANTOM_KEY" "https://localhost:3000/api/agent/$p"
done
```

## Build & contribution contracts (agent behavior: MANDATORY)

### Pre-deploy gate (MANDATORY before every push)

Before pushing source that triggers any per-service build, run all four locally (CI runs the same checks, only slower):

```bash
cd mcp/agent
npx tsc --noEmit                  # type-check (TS)
npm run lint                      # ESLint (TS)
npm run build                     # full Next.js production build — catches strict route validation
cd ../../bundles/spark/mcp
PYTHONPATH=$PWD/src python3 -m pytest tests/ -x   # embedded MCP tests (~7-8s, ~421 tests)
```

**`PYTHONPATH=$PWD/src` is REQUIRED.** Half the test files use `from usecase.X import Y` which needs `src/` on the path.

**Why all four.** `tsc` catches type errors but is happy with stale eslint-disable directives. `lint` catches unconfigured-rule references but doesn't run Next.js's strict Route-type validation. **Only `npm run build` catches everything TS-side**, including strict-route validation. **`pytest` covers the Python embedded MCP side.**

If any fails locally, fix before pushing.

### Feature completeness contract (MANDATORY — UI ships with the backend)

Every feature ships as a **complete unit**: backend, MCP surface, UI surface, agent-side proxies, docs. **No piece-by-piece delivery.** A "feature" is operator-defined — when the operator says "add X" the deliverable is "the operator can use X end-to-end."

**Before declaring a feature complete, verify ALL of these were touched:**

1. **Backend** — Python in `bundles/spark/mcp/src/`, connector source under `bundles/spark/connectors/<id>/src/`, or wherever the logic lives.
2. **MCP surface (if applicable)** — new MCP tool registered, or REST endpoint added under `bundles/spark/mcp/src/api/`.
3. **`connector.yaml` (if a connector tool was added)** — entry in `spec.tools[]` matching the new function. Otherwise the agent's catalog won't see it.
4. **Agent-side proxy (if a new REST endpoint was added)** — `mcp/agent/app/api/agent/<resource>/route.ts` that forwards to the MCP via `resolveMcp()`. UI code can't reach the MCP directly.
5. **UI surface** — every operator-visible feature gets a UI affordance in the SAME release. New page → `app/<feature>/page.tsx` + sidebar entry. New action → button/modal/panel on the relevant existing page. **Every operator-visible JSON endpoint that the UI reads from must be audited when a feature lands; a forgotten hand-maintained route shows stale data.**
6. **Hardcoded-data audit** — when a feature changes the shape, count, or list of something the UI displays, grep for ALL paths the UI could read that data from. `grep -rn "<entity-name>" mcp/agent/app/api/` catches static/hardcoded fallbacks that drift. The `/api/marketplace/connectors` route once carried a hand-maintained `toolCount` array that nobody updated as the tool surface grew. **The check that catches it: `curl /api/marketplace/connectors | jq '.[] | {id, toolCount}'` before declaring a connector feature complete.**
7. **Docs + journeys** — per the existing § Documentation discipline + § Pre-release docs checklist, every operator-visible change updates `/help/architecture`, `/help/user`, `mcp/agent/lib/journeys.ts`, `CHANGELOG.md`, `mcp/agent/lib/release-notes.ts`.
8. **Endpoint audit** — verify EVERY endpoint the UI reads for the feature's data. If the feature has a `toolCount` shown in the UI, assert the served `toolCount` is correct from the actual route the UI consumes.

**Forbidden anti-patterns**:
- ❌ "Backend infrastructure ships now; UI lands in v0.X.Y+1" — every feature ships its UI in the same release, not a follow-on
- ❌ Validating a feature via a NEW endpoint while the UI continues to read a DIFFERENT (stale) endpoint
- ❌ "The UI will pick it up automatically" without checking the data path the UI actually reads
- ❌ Adding new MCP tools without verifying they appear in the marketplace catalog endpoint that the cards display

**Litmus test before declaring a feature done**: open the relevant UI page on a running install, take a screenshot OR fetch the API endpoint the UI reads, and confirm the feature's deliverable is visible there. If I can't see it on the UI, the feature isn't done.

## Pre-build context refresh (MANDATORY — every build)

**Before starting work on any new build (feature, fix), refresh context by reading the docs that describe what was already implemented and how it's specified.** Drift between code, spec, UI, and docs is the single largest source of regressions. The way to prevent drift is to enter every build with current knowledge of what exists.

### What to read before touching code

For any non-trivial build, open and skim ALL of:

| Doc | Why |
|---|---|
| **`CHANGELOG.md`** (last 3-5 entries) | Recent operator-language deltas. |
| **`mcp/agent/lib/release-notes.ts`** (last 3-5 entries) | Version-bundled bullets shipped with each release. |
| **`mcp/agent/app/help/architecture/page.tsx`** | Canonical SPEC for substrate behavior. |
| **`mcp/agent/app/help/user/page.tsx`** | User-facing feature descriptions, tagged by version. |
| **`mcp/agent/lib/journeys.ts`** | Click-paths through the product. |
| **`mcp/agent/app/observability/**`** | Runtime-introspection surfaces. |

The 5-15 minutes of skim-time pays for itself ten times over by preventing "oh, that already existed, I just re-built it differently" drift.

Then plan changes that conform to the spec, run the pre-deploy gate, and finish with the docs checklist. Skip either end of "read before code, write after build" and the drift returns.

## Data-source validation doctrine (MANDATORY — syslog/CEF ONLY)

When onboarding, simulating, or validating a data source against Cortex XSIAM, follow the **`data-source-xdm-validation` skill** (auto-activates on `bundles/spark/data-sources/**`).

**What counts as a data source (the admission rule — check this BEFORE adding any vendor):** A Phantom data source MUST correspond to a real Cortex XSIAM **log-ingestion + parsing path** — the vendor has a **parsing rule and/or modeling rule** (shipped in a content pack OR built-in/native to the platform, e.g. PingFederate's native authentication parser) so its logs land in a dataset and get *structured*. **A vendor whose only Cortex presence is an XSOAR/Marketplace integration with no Parsing/Modeling rules is NOT a data source — it is an action integration** (it fetches alerts/incidents or runs response actions via API; it does not ingest+parse logs into a dataset). **Do not add action integrations to the data-source catalog.** SIEMs that are log *destinations* (IBM QRadar, Rapid7 InsightIDR) are likewise not sources. Litmus: does Cortex ship/native a parsing or modeling rule that produces structured columns/`xdm.*` for this vendor? No rule anywhere → not a data source. (Vendors such as CrowdStrike, Sophos, PingOne, Wiz, Rapid7, SAP, ESET, Snowflake and Veeam fail this test; PingFederate passes through its native parser.)

The load-bearing rules, which govern every data-source decision:

1. **Phantom ALWAYS delivers synthetic logs over syslog/CEF to the Cortex Broker. NEVER an HTTP collector or API integration — full stop.** This holds even when the real-world vendor is collected that way in production (CrowdStrike FDR pulling from S3, Snowflake/Wiz/Rapid7/PingOne API pollers, HTTP event collectors). `phantom_create_data_worker` is always `type=CEF` (or SYSLOG/LEEF) to a `udp:<broker>:514` destination. **One sanctioned exception:** the `http-sender` bundle connector (`bundles/spark/connectors/http-sender/`) sends JSON to an XSIAM HTTP Log Collector when the operator chooses to — for HTTP-versus-CEF A/B tests, and for **HTTP-delivery data sources** (`delivery: http` in `data_source.yaml`; `Okta`/`ProofpointTAP`/`GoogleDrive` `*HttpCollector` today). An HTTP data source exists for HTTP simulation: it never replaces syslog/CEF for validating or promoting a data source's mapping, it carries no `validated`/`raw_validated` tier (those belong to the syslog/CEF path), `phantom_create_data_worker` is not used for it, and it is never an API poller. The admission rule below still applies to it: a real parsing/modeling path must exist for the vendor. **Pairing:** where a vendor has both a syslog source and an HTTP one (Okta, Proofpoint TAP, Google Drive), the syslog one is for checking parsing and modeling and its `how_to_use` says to expect no Analytics alerts from it; to test Analytics the operator uses the HTTP one with `http-sender` (for Okta and Proofpoint TAP the strongest route is the `cribl_<source>` destination). Cortex collects all three with its own API collectors, not an HTTP collector; saying their official collection is HTTP is wrong. **Second sanctioned exception:** the `wec-sender` bundle connector (`bundles/spark/connectors/wec-sender/`) delivers Windows Event XML to the Broker VM's Windows Event Collector applet over WS-Management (mutual TLS, TCP 5986) when the operator chooses to. It exists because `_collector_type = WEC` is stamped by the collection path and cannot be set from an event body, so the parsing rules, Analytics detectors and `xdr_data` entities that depend on a Windows Event Collector are unreachable over syslog/CEF. It has the same limits as `http-sender`: it never replaces syslog/CEF when validating or promoting a data source's mapping, it carries no `validated`/`raw_validated` tier, `phantom_create_data_worker` is not used for it, and it sends only to the operator's own broker with the operator's own client certificate (never an API poller, never a remote executor).
2. **Why it's sound:** the broker, parsing rules, and modeling rules are **protocol-agnostic** — they map on the **data shape** (field/column/JSON structure), not on how the event arrived. A rule reading `json_extract_scalar(evt, "$.a.b")` maps our event whether it came via API or syslog, as long as it carries `a.b` in the expected shape. **That claim covers parsing and modeling only, not Cortex Analytics:** one Okta FastPass event that landed in `okta_sso_raw` over both paths with identical columns and `xdm.*` fields alerted when sent through the HTTP collector and raised nothing over syslog/CEF (observed in a side-by-side test). The cause is not established (the collector-type stamp and a registered data-source stream both fit), so never promise an Analytics alert from a syslog/CEF source whose Cortex collector is an API or HTTP collector (Okta, Proofpoint TAP, Google Workspace): reproduce its native feed through `http-sender` (the generic HTTP collector, or the Cribl integration with the source's dedicated UUID) or `wec-sender` for Windows.
3. **The job is reverse-engineering, not transport.** Read the vendor's parsing + modeling rules → derive the exact field shape they expect (names, types, JSON paths, value types, the gate) → encode it into `data_source.yaml` `fields[]` (name + type + description + example) and `how_to_use` → the agent crafts events of that shape → ships them as CEF → the rules parse + map → `xdm.*` populates → validated.
4. **Corrections this enforces:** a vendor being "native-collector-only"/"API-integration" is **irrelevant** to validatability — never dismiss it for that reason. `raw>0, xdm=0` means **no modeling rule is bound** (not "can't map") — obtain + reverse-engineer the rule. The `how_to_use` documents the **data shape + syslog/CEF routing literal**, NOT the vendor's real-world collection plumbing (describing "FDR S3/SQS" as the *mechanism* misleads the agent into thinking it needs an HTTP collector — it never does).

See the skill's `## Delivery doctrine` section + `references/diagnostic-playbook.md` for the full loop.


### Routing literal lives in `how_to_use`, NOT in `vendor`/`product`

A `data_source.yaml`'s `vendor`/`product` are **display labels** — the Cortex marketplace
pack's names (`Duo Security`/`DuoAdminApi`). They are NOT the CEF wire header. The literal
the broker actually routes on is documented in `how_to_use` as an explicit block:

```
Required CEF header for XSIAM:
- vendor: `duo`
- product: `duo`
```

Duo displays as `Duo Security`/`DuoAdminApi` but routes as `duo`/`duo` → `duo_duo_raw`.
**Do not "fix" `vendor`/`product` to match the dataset name** — 261 of 295 sources differ
from their derived name and 24 of those are validated and working. That difference is the
convention, not a bug.

**How to find the right literal, in order:**

1. **If the pack ships a parsing rule, read its `[INGEST: …]` block** — it hands you the
   literal verbatim, plus the `_time` parse and the `no_hit` behaviour.
2. **Otherwise the broker derives** `<lower(vendor)>_<lower(product)>_raw`, lowercasing and
   replacing non-alphanumerics with `_`. Reverse that from `dataset_name`
   (`aws_guardduty_raw` → `AWS`/`GuardDuty`).
3. **Some dataset names are not derivable** (`imperva_inc__securesphere_raw`). Those route
   by the vendor's canonical CEF header (`Imperva Inc.`/`SecureSphere`) — look it up and
   confirm empirically which dataset the events land in.
4. **Always verify** the events landed where you intended, and that `unknown_unknown_raw`
   did not grow.

### Shared vendor/product pairs need an in-event discriminator

Several packs claim the SAME pair and are separated by a `filter` inside their INGEST
block. Get the discriminator wrong and the event routes to a sibling's dataset — silently,
because it still lands somewhere. Get the PRECONDITION wrong and it lands nowhere at all.
The `microsoft`/`windows` family is **six** packs sharing one header (checked against the
mirrored parsing rules; Sysmon and MicrosoftCore are easy to overlook):

| Dataset | Pack | no_hit | Discriminator |
|---|---|---|---|
| `microsoft_amsi_raw` | MicrosoftWindowsAMSI | drop | `provider_name = "Microsoft-Antimalware-Scan-Interface"` |
| `microsoft_sysmon_raw` | MicrosoftWindowsSysmon | drop | `provider_name = "Microsoft-Windows-Sysmon"` |
| `microsoft_adfs_raw` | MicrosoftADFS | drop | `provider_name IN ("AD FS Auditing","AD FS")` **AND `_collector_type = "WEC"`** — unreachable over syslog/CEF (derived route below); reachable over a real WEC delivery (`wec-sender`) |
| `microsoft_dns_raw` | MicrosoftDNS | drop | `_raw_log` matches `M/D/YYYY h:mm:ss AM` (branch B needs `_raw_log = null`, impossible over syslog) |
| `microsoft_windows_raw` | MicrosoftWindowsEvents | drop | `provider_name` NOT IN the four above |
| `microsoft_windows_raw` | MicrosoftCore | **keep** | `time_created != null` — the only catch-all in the family |

**`time_created` is a precondition for the WHOLE FAMILY, and it is the one that bites.**
Five of the six filter on `to_string(time_created) ~= ".*\d{2}:\d{2}:\d{2}.*"` before they
look at `provider_name` at all, and five of the six are `no_hit=drop`. An event without a
parseable `time_created` therefore matches nothing and is DISCARDED — no dataset, no error,
no `unknown_unknown_raw` row. For example, a well-formed LDAP-Client event sent
with a 13-field `schema_override` that omits `time_created` lands **zero rows**; the
identical event with `time_created` added lands and models. **When you send a field
SUBSET to this family, `time_created` is not optional.**

If a pack's `provider_name` example is a placeholder such as `sample_name`, the event routes to
`microsoft_windows_raw` whichever pack it was meant for. **A gate field whose `example` is a
placeholder is a routing bug**, not a cosmetic one — the validator's gate-field check exists
for exactly this.

### When a parsing rule gates on unseedable meta — use the derived route

Some pack parsing rules gate on ingestion-stamped meta that no event body can set.
`_collector_type` is the canonical case: the broker stamps it (**`"Syslog"`** on our path,
`"WEC"` for a Windows Event Collector), and a CEF extension key of the same name is
**shadowed, not honoured** — verified empirically. Its documented source is "Log Metadata"
only, unlike `_vendor` ("Raw log or Parsing Rule") and `_product`.

**One path does stamp `WEC`: a real Windows Event Collector delivery** (`wec-sender`). For example, a provider `AD FS Auditing` event sent to the Broker VM's applet landed in `microsoft_adfs_raw` through the pack's own parsing rule and modelled 28 `xdm.*` fields. Use the derived route below only when the event must travel over syslog/CEF.

**No tenant-side rule can rescue this.** INGEST sections are standalone and never chain —
*"all rules inside a group get evaluated independently"* — so nothing an operator authors
becomes the input to the pack's filter. A custom rule keyed on the shared pair would also
run against every sibling source's traffic.

**The bypass: route by an unclaimed vendor/product pair whose derived name equals the
target dataset.** No INGEST block claims `microsoft`/`adfs`, and that pair derives
`microsoft_adfs_raw` — the exact dataset the modeling rule binds to. The parsing rule is
never consulted, its `no_hit=drop` never fires, and the modeling rule (which binds by
dataset **name only**) still applies. End to end, a single CEF
probe lands and maps `xdm.event.id` + `xdm.observer.type`.

Before relying on it, check `dataset = <target> | limit 1`. If the dataset has never
received data there is nothing to collide with; if it has, confirm the existing schema
does not conflict. PANW ships this same mechanism in production — the IllusiveNetworks
pack has **no parsing rules at all** and reaches `illusive_illusive_raw` purely by
derivation.


### Fixed param ranges must be fully populated

Several modeling rules concatenate a fixed range of fields into one string before parsing
it — the ADFS rule builds `raw_param_2 + raw_param_3 + … + raw_param_15`. **A single
missing member nulls the whole concatenation and silently poisons the rest of the rule.**
You get the handful of fields assigned before the concat and nothing after, with no error
anywhere: no parsing-rule error row, no null-vs-missing distinction, just a thin result
that looks like a mapping problem.

Unused members must carry the vendor's filler value, not be omitted. The tell is in the
rule itself — ADFS has an explicit `if(raw_param_N = "-", replace(...), …)` branch, which
means real events populate all fifteen and use `"-"` for the empties. **When a rule
special-cases a literal like `"-"`, that is the vendor's convention and the schema must
reproduce it.**

On ADFS, `param2` alone → 9 XDM fields null. `param2` plus `param3`–`param15`
set to `"-"` → all of them populated, including `xdm.source.user.upn` and
`xdm.auth.auth_method`.

Related, same failure signature: **JSON composites must be JSON OBJECTS on the wire.** A
CEF extension literally named `event_data.param2=…` produces a flat column of that name,
which `json_extract_scalar(event_data, "$.param2")` cannot read. Declare dotted-leaf
fields in `data_source.yaml` so the generator builds the nested object; nested JSON
survives CEF-over-syslog intact, XML payloads included.

## Architecture page is the spec (MANDATORY — read before editing)

[mcp/agent/app/help/architecture/page.tsx](mcp/agent/app/help/architecture/page.tsx) is the **canonical specification** for how Phantom's substrate behaves. It describes the target state — not just what the code currently does. When the code and the architecture page disagree, **the architecture page wins** and the code is the gap that needs fixing.

**Before editing any of the following code paths, READ the architecture page sections that govern them:**

| Code path | Required architecture-page section |
|---|---|
| `lib/runtime-config.ts`, `app/api/agent/providers/config/*`, `app/providers/page.tsx`, `app/api/auth/change-password/*`, `app/profile/page.tsx` | `#setup-wiring` |
| Connector instances | `#instance-store`, `#setup-wiring` |
| Provider instances | `#provider-store`, `#setup-wiring` |
| TLS, cert generation, SSL_CERT_PEM/SSL_KEY_PEM, /tls/ volume | `#tls-proxy` |
| Per-instance connector containers | `#connector-containers` |
| MCP / agent topology, ports, auth surface | `#stack` |
| Data sources | `#data-sources` |

**The rule**: if about to change behaviour in any of those areas, open the architecture page first and confirm what you're about to do conforms to the spec. If it doesn't, EITHER update the code to match the spec, OR get explicit operator approval to update the spec itself + update the page in the same PR.

**Don't silently drift.** When the architecture page describes target state the code doesn't yet meet, the gap goes in the section's `Implementation gap` subsection. If you fix one, remove the bullet in the same PR — the gap list is a living checklist, not a permanent record.

## Documentation discipline (MANDATORY — every release)

Every release ships a coherent platform: code, **and** the docs that explain it. Backend changes that aren't reflected in the UI surfaces and help pages are bugs — silent gaps that confuse users and rot under future work.

### Pre-release docs checklist

Before tagging any `v*.*.*`, every backend feature merged since the last release must have:

1. **Architecture page reflects reality** ([mcp/agent/app/help/architecture/page.tsx](mcp/agent/app/help/architecture/page.tsx)). Service list matches `docker compose ps -a`. Every new service has a section with container name, source path, runtime, host ports, role, **explicit inter-service connections**. Removed services are removed. Volume mounts, build args, env-var contracts current.
2. **User guide reflects every operator-visible feature** ([mcp/agent/app/help/user/page.tsx](mcp/agent/app/help/user/page.tsx)). For every PR adding a UI affordance, a corresponding paragraph or subsection. Tag new content with the introducing version. **Removed/changed features need their description updated or removed in the same PR.**
3. **User journeys cover every documented flow** ([mcp/agent/lib/journeys.ts](mcp/agent/lib/journeys.ts)). Each journey is a click path. Add when a flow ships; retire when a flow goes away.
4. **Observability surfaces reflect runtime reality** ([mcp/agent/app/observability/](mcp/agent/app/observability/)). Silent telemetry that doesn't surface in observability is rot waiting to happen.
5. **Skills page (`mcp/agent/app/skills/page.tsx`) in sync with on-disk skills.** Hardcoded `SKILLS: SkillDef[]` array IS allowed to lag (live fetch covers current state) but clean up when it drifts.
6. **No backend feature without a UI surface (or a documented deferral).** For every new MCP tool / `/api/agent/*` endpoint / config knob: either (a) a UI page or panel, or (b) a code comment + help-docs note "API-only for now". Silent endpoints rot.

6a. **No new UI page without a sidebar nav entry in the SAME release** . Grep test before committing: `find mcp/agent/app -maxdepth 3 -name 'page.tsx' | xargs dirname | sort` vs the `href:` entries in `mcp/agent/components/sidebar.tsx`'s `navEntries`. Every page (except redirects + `[param]` dynamic routes) should appear. If deliberately operator-hidden, document with a code comment near `export default`.

7. **Release notes describe user-visible deltas — in BOTH places.** [CHANGELOG.md](CHANGELOG.md) (long-form, operator language). [mcp/agent/lib/release-notes.ts](mcp/agent/lib/release-notes.ts) (3-7 highlights, ~10-15 words each, **newest first**). They ship together; operators see them on upgrade.
8. **Spec drift is fixed in the same PR, not deferred.** "I'll fix this in a follow-up" is the lie that ships documented-but-broken features.
9. **MCP tool docstrings stay in lockstep with UI forms.** When a UI form field is added/changed/removed on a system-management page, the matching MCP tool's docstring (`bundles/spark/mcp/src/usecase/builtin_components/self_mod_tools.py`) MUST be updated in the same PR. The agent picks fields by reading the docstring, not just the signature. **Operator-visible UI form changes without docstring updates are silent capability gaps.**

   For a new UI form field: identify the matching MCP tool. Add to docstring Args: parameter name, type, default, what it does, **when the agent should set it** (concrete trigger phrases work — *"set when the operator says 'don't ask me each time'"*). For discriminated-union actions, update the example shapes. For destructive parameters, flag in the docstring.

## Quality-first principle (MANDATORY — enterprise product)

Phantom is an **enterprise product**. The bar for code quality is not "the test passes"; it's "the change fits cohesively into the existing architecture, the spec stays consistent, and the next person inheriting it doesn't have to untangle a shortcut."

When fixing issues during a build, the priority order is:

1. **Standard architecture first.** If the existing pattern in the codebase solves your problem, use it. New abstractions must be justified explicitly and wired into existing infrastructure, not alongside.
2. **Clean cohesive builds over random patching.** "Minimal-diff fix" is only minimal if it's also coherent. Patching one symptom while leaving the root cause unchanged creates compounding debt.
3. **Spec consistency over speed.** Drift from the architecture page → update the page in the same PR OR back out the change.
4. **No "I'll fix it in a follow-up" debt** unless explicitly marked with a code comment.
5. **Token / effort cost is not a reason to take a shortcut.** Burn the tokens, take the longer code path. If a clean fix needs 3x the diff size, it's still the right fix.

### Concrete anti-patterns to avoid

- **Stapling instead of integrating.** New endpoint duplicating 70% of an existing one — refactor the existing one instead.
- **Symptom suppression.** try/except that swallows an unexpected error to make the test pass. Investigate.
- **Magic-number config.** Wire through `pydantic-settings` from the start.
- **Drive-by partial documentation.** Updating CHANGELOG but not release-notes.ts; updating architecture but not user-guide. Either do the full doc cycle or don't claim the build is done.
- **"It works on my machine."** Phantom is a multi-container stack. Always smoke-test against a running install of the built images, not just unit tests.

### Inter-service connections — emphasize these

When updating architecture docs, **the connections between services matter as much as the services themselves**. For every service-to-service call document:

- Source service + outgoing port
- Destination service + listening port
- Auth mechanism (bearer token? cookie? mTLS? unauthenticated?)
- Failure mode (retries? circuit breaker? graceful degrade?)
- Whether the call is sync or async

Example: *`phantom-agent` (Next.js, port 3000) → embedded MCP subprocess (Python FastMCP, port 8080) — bearer auth via `MCP_TOKEN`, in-process loopback over HTTPS, ~5s timeout, no retry. The agent proxies every `/api/agent/*` call to the MCP at `/api/v1/*` via [lib/mcp-proxy.ts](mcp/agent/lib/mcp-proxy.ts).*

Boxes-with-labels diagrams are not enough. Drift hides in the wires.

## Canonical-state discipline (MANDATORY — applies to every refactor)

The authentication design collapses what could have been five separate auth-state stores into one, carries no legacy fallback path, and ships its documentation + journeys + diagrams + observability coverage in the SAME release. These five rules apply the same principles to every refactor.

### Rule 1 — One state surface = one storage home

Every persisted value lives in **exactly one** place. No fallback chains, no env-var override at the read path, no "try X first, fall back to Y." The architecture page documents that one home; the code reads from it without compatibility shims.

**Before adding new persisted state**: *"Where will this value live? Is there an existing surface that owns this concept already? If two surfaces could own it, which one becomes canonical and which one becomes a delete?"* The wrong answer is "both, with sync between them."

### Rule 2 — When you refactor a state surface, delete the legacy paths in the SAME release

Migration code is a regression magnet: more branches than the new path, more failure modes, operators trip on it for years after the cutover. Concrete example: when the `SecretStore` hash path became the canonical credential store, the old plaintext-compare path did not get a deprecation warning — it was deleted from the route handler, its env vars were removed from compose, its config file was removed from the repo + install kit, and the operator-facing `/setup` page was deleted entirely.

**Safety requirement**: a complete operator-facing communication plan (CHANGELOG + release-notes + architecture #section + user-guide #section + journeys) AND a fresh-volume install test before the deletion lands.

**Does NOT require**: automatic migration tooling. Operators get clear release notes + a CLI to recover.

### Rule 3 — Derive runtime state from observable evidence, not env vars that mid-process scripts mutate

Example: `entrypoint.sh` flips `MCP_URL` from `http:` to `https:` in its own process scope. But `docker exec` inherits the **image's original env config** (unflipped), not the entrypoint's in-process mutation. A CLI that trusts `MCP_URL` POSTs plain HTTP to a TLS-only listener and gets `other side closed`.

So derive from **observable filesystem state** instead. The CLI checks `existsSync("/tls/cert.pem")` — the cert is physically on disk, independent of which process tree you arrived through.

**General principle**: env vars are fragile across process boundaries. If a code path can be invoked from outside the entrypoint's process tree (`docker exec`, sidecars, debuggers), it must derive runtime state from observable evidence (file existence, cert presence, lockfile content).

### Rule 4 — Operator-facing surfaces don't carry developer context

Design context (what we're building toward, why a feature is limited, internal references) goes in code comments OR the developer-facing architecture page OR CHANGELOG.md — **not on operator-facing UI pages**. The operator-facing path for "how do I reset my password" is the user guide at `/help/user#authentication`, not a paragraph wedged into `/profile`.

**Practical test before shipping any UI text**: would an operator who installed the product yesterday be confused by this sentence? If it references "this version vs the roadmap," internal mechanics, or "we used to do X but now we do Y," it doesn't belong on an operator-facing page.

### Rule 5 — Retire docs + journeys + diagrams in the SAME release that retires the code

Deleting a host script isn't done until the journey that walked operators through running it is also retired. Otherwise six months later an operator finds the stale journey via google, types the command, gets "command not found," and has no idea what's authoritative.

**Stub-comment over silent deletion**: a retired journey ID stays in `journeys.ts` as a `// [vX.Y.Z] Retired: <id>. Replaced by <new-id> because <reason>` comment, NOT a raw `git rm`. Same for architecture-page sections. The comment is a breadcrumb for future debugging.

### How to apply this rule to a future refactor

1. **Enumerate every storage location** the current state lives in.
2. **Pick ONE as canonical.** The others become deletes, not stale-fallback shims.
3. **Plan the deletion calendar**: what code gets deleted, what env vars get removed from compose, what files get removed from the install kit, **AND what CI workflows / release scripts / installer templates reference the file.** The cheap check: `grep -rn <filename> .github/ installer/ scripts/ mcp/agent/lib/ mcp/agent/app/help/` BEFORE declaring the deletion plan complete.
4. **Plan the docs calendar**: architecture-page section to rewrite, user-guide section, journeys to retire, CHANGELOG + release-notes entries, diagrams.
5. **Plan the observability surface**: what events does the new path emit? Are they visible in `/observability/events`?
6. **Test the full operator path** through the real installer on a fresh install (NOT `docker compose up -d --force-recreate`).
7. **Same release ships** code deletion + docs replacement + journey retirement + diagram update.

If you find yourself thinking "I'll delete the legacy fallback later" or "the docs can lag one release," you're recreating the classic migration trap. **Do it together or don't do it at all.**
