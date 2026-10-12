# Phantom — Codebase Map

A lightweight map of the repo so an agent can find where a feature lives
*before* it starts reading files. Layered: top-level groups first, then the
modules inside each. Keep this current when you add or move a service.

## Top level

| Path | What it is |
|------|------------|
| `mcp/agent/` | The chat UI + embedded MCP subprocess (the **`phantom-agent`** container). Next.js 15 + React 19 + Python 3.12. |
| `bundles/spark/` | Phantom's runtime bundle — the MCP server, the per-instance connector containers, default skills, plugins, KBs, prompts, providers, and caldera content. |
| `xlog/` | Log-generation backend (the **`xlog`** container). FastAPI + Strawberry GraphQL + the vendored `app/logforge` generation engine. |
| `installer/` | Installer template + docker-compose.yml. |
| `updater/` | The **`phantom-updater`** container — manages per-instance connector container lifecycle + stack-level upgrades. |
| `phantom-browser/` | Dockerfile only — headless Chromium for the web connector (CDP-accessed). |
| `phantom-connector-runtime/` | Shared base image for container-style per-instance connectors. |
| `docs/` | Long-form docs (architecture, quickstart, split-deploy, API reference). |
| `.github/` | Issue templates. |
| `scripts/` | One-off maintainer scripts (e.g. `refresh_cortex_baked_catalog.py`). |
| `examples/` | Reference snippets — never imported by runtime code. |
| `tests/` | Cross-repo smoke; per-service tests live beside the service. |
| `reports/` | Audit + analysis artifacts (gitignored from agent context via `.claudeignore`). |
| `diagrams/` | Source for architecture diagrams (`.excalidraw`, `.svg`). |

## bundles/spark/ — the Phantom runtime bundle

| Path | What it is |
|------|------------|
| `bundles/spark/mcp/` | The Python FastMCP server that runs as a subprocess inside `phantom-agent`. Registers ~80 tools, exposes REST routes for the Next.js side. |
| `bundles/spark/connectors/` | Per-connector source: each subdir is one connector (`xlog`, `xsiam`, `caldera`, `cortex-content`, `cortex-docs`, `cortex-xdr`, `web`, `http-sender`, `wec-sender`). Each runs as its own image, built at release time. |
| `bundles/spark/skills/` | Default skills shipped with the agent (MD files with frontmatter). Volume-seeded on first boot; merged on per-release marker. |
| `bundles/spark/plugins/` | Built-in plugins (bundled vendor extensions). |
| `bundles/spark/kbs/` | Knowledge base entries (XQL examples, etc.) seeded into ChromaDB at boot. |
| `bundles/spark/prompts/` | System-prompt fragments. |
| `bundles/spark/providers/` | Provider-specific glue (Vertex AI, Gemini). |
| `bundles/spark/caldera-content/` | Caldera plugin content (abilities, adversaries). |

## mcp/agent/ — the agent UI + embedded MCP host

| Path | What it is |
|------|------------|
| `mcp/agent/app/` | Next.js App Router pages + API routes. |
| `mcp/agent/app/(main)/` | Main app routes (sidebar-grouped). |
| `mcp/agent/app/api/` | API routes — `auth`, `chat`, `skills`, `marketplace`, `agent`. The `/api/agent/*` set are thin proxies to the embedded MCP via `lib/mcp-proxy.ts`. |
| `mcp/agent/app/help/` | In-product help — `architecture/page.tsx` (canonical spec), `user/page.tsx` (operator guide), `journeys/` (click-paths), `api/` (REST reference). |
| `mcp/agent/app/observability/` | Runtime introspection — `events`, `logs`, `metrics`, `traces`, `cost`, `pipeline`, `connectors`, `runtime-events`. |
| `mcp/agent/components/` | Shared React components. `sidebar.tsx` is the nav source of truth. |
| `mcp/agent/lib/` | Shared TS — `mcp-proxy.ts`, `journeys.ts`, `release-notes.ts`, `system-prompt.ts`, `runtime-config.ts`. |
| `mcp/agent/entrypoint.sh` | Container start: TLS proxy + MCP subprocess + Next.js. |
| `mcp/agent/tls-proxy.js` | Node.js sidecar terminating TLS in front of UI (3000) + MCP (8080). |

## bundles/spark/mcp/ — the embedded Python MCP server

| Path | What it is |
|------|------------|
| `bundles/spark/mcp/src/config/config.py` | `pydantic-settings` config — every env var goes through `validation_alias`. |
| `bundles/spark/mcp/src/service/` | FastMCP instance factory. |
| `bundles/spark/mcp/src/usecase/builtin_components/` | Tool implementations. Each module groups related tools (`data_faker`, `workers`, `scenarios`, `xsiam_tools`, `caldera_tools`, `simulation_skills`, `skills_crud`, `observables_catalog`, `field_info`, `job_scheduler`, `marketplace`, `secrets_store`, `self_mod_tools`). |
| `bundles/spark/mcp/src/usecase/connector_loader.py` | Dynamic registration of connector tools at boot. |
| `bundles/spark/mcp/src/api/` | REST routes that the Next.js side proxies (`instances.py`, `providers.py`, `data_sources.py`, etc.). |
| `bundles/spark/mcp/src/pkg/` | Shared clients — `graphql_client` (xlog), `papi_client` (XSIAM), `caldera_factory`, `xql_rag_service` (ChromaDB + sentence-transformers). |
| `bundles/spark/mcp/src/main.py` | Entry point. Registers ~80 tools in one block inside `async_main`. |
| `bundles/spark/mcp/tests/` | pytest suite (~421 tests). Run with `PYTHONPATH=$PWD/src python3 -m pytest tests/ -x`. |

## bundles/spark/connectors/ — per-instance connectors

Each connector ships as its own image at release time. The agent dispatches to per-instance containers via HTTP, not in-process Python.

| Connector | What it does |
|-----------|--------------|
| `xlog` | Phantom's log-generation tools (wraps the xlog service GraphQL). |
| `xsiam` | XSIAM PAPI integration — XQL queries, alerts, datasets. |
| `caldera` | Caldera red-team operations. |
| `cortex-content` | Cortex content catalog (data sources, packs, modeling rules) — local catalog at `bundles/spark/connectors/cortex-content/baked/`. |
| `cortex-docs` | Cortex documentation search (embedded vector index). |
| `cortex-xdr` | Cortex XDR API (cases, issues, alerts). |
| `web` | Web browsing via Playwright + headless Chromium (phantom-browser CDP). |
| `http-sender` | Sends synthetic JSON events to an XSIAM HTTP Log Collector or the Cortex Cribl endpoint (event profiles for Okta, Proofpoint TAP, Google Workspace, AWS, GCP, Azure AD, Windows). |
| `wec-sender` | Delivers synthetic Windows events to the Broker's Windows Event Collector over WS-Management with mutual TLS. |

## xlog/ — the log-generation backend

| Path | What it is |
|------|------------|
| `xlog/main.py` | FastAPI app, mounts Strawberry GraphQL at `/`. |
| `xlog/app/schema.py` | All GraphQL queries + mutations. Active workers live in a module-level `workers = {}` dict (no persistence). |
| `xlog/app/types/` | Strawberry enums + dataclasses (`datafaker.py`, `scenarios.py`, `sender.py`). |
| `xlog/app/dynamic_schema.py` | Schema-override value generator for `generate_fake_data_v2`. |
| `xlog/scenarios/ready/*.json` | Pre-built scenario files. |
| `xlog/config.yml` | Worker count, log rotation, XSIAM parsed fields. Mostly env-var overridden. |

## installer/ + updater/ — packaging + lifecycle

| Path | What it is |
|------|------------|
| `installer/docker-compose.yml` | Install compose — image refs use `@${DIGEST_*}` for content-pinning. |
| `installer/build-phantom-installer.sh` | Builds the self-extracting `phantom-installer` from `phantom-installer.template.sh`. |
| `updater/src/main.py` | The `phantom-updater` daemon — manages per-instance connector container lifecycle. |
| `updater/Dockerfile` | Builds the `phantom-updater` image. |

## Finding a feature

- **A chat-UI page** → `mcp/agent/app/(main)/<feature>/page.tsx`.
- **A help-page section** → `mcp/agent/app/help/architecture/page.tsx` or `.../user/page.tsx`.
- **An API endpoint** → `mcp/agent/app/api/agent/<resource>/route.ts` (Next.js proxy) → `bundles/spark/mcp/src/api/<resource>.py` (MCP backend).
- **An MCP tool** → `bundles/spark/mcp/src/usecase/builtin_components/<file>.py` registered in `bundles/spark/mcp/src/main.py`.
- **A connector tool** → `bundles/spark/connectors/<connector>/src/`.
- **A skill** → `bundles/spark/skills/<category>/<name>.md`.
- **Log-generation behavior** → `xlog/app/schema.py` (mutations) + `xlog/app/types/` (enums).
- **A release entry** → `CHANGELOG.md` (long-form) + `mcp/agent/lib/release-notes.ts` (About modal).
- **A user journey** → `mcp/agent/lib/journeys.ts`.
- **An issue template** → `.github/ISSUE_TEMPLATE/` (`bug_report.md`, `feature_request.md`).
