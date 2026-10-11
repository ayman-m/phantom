# AGENTS.md

This file provides guidance to Codex (and other coding agents that read `AGENTS.md`) when working with code in this repository.

**The repo-wide rules live in [`CLAUDE.md`](CLAUDE.md) and apply to every coding agent, not only Claude Code.** Read it first: it holds the defensive-purpose statement, the credential guardrail, the data-source validation doctrine, the architecture-page-is-the-spec rule, documentation discipline and the pre-deploy gate. Per-subsystem conventions live in the `CLAUDE.md` file of each directory (`mcp/agent/`, `bundles/spark/mcp/`, `bundles/spark/connectors/`, `xlog/`, `installer/`, `updater/`). The structural map is [`CODEBASE_MAP.md`](CODEBASE_MAP.md); the harness (hooks, skills, subagents, MCP servers) is described in [`AI-LAYER.md`](AI-LAYER.md).

## What Phantom is

Continuous SOC simulation platform: synthetic security log generation, scenario-based MITRE ATT&CK telemetry, and AI-orchestrated red/blue workflows over MCP. It is a **defensive detection-engineering tool**: everything it emits is synthetic telemetry sent only to the operator's own Cortex XSIAM broker and tenant. Ships as a Docker Compose stack.

## Stack topology

| Service (container) | Source | Language | Host port | Purpose |
|---|---|---|---|---|
| `xlog` | [xlog/](xlog/) | Python 3.12 (FastAPI + Strawberry GraphQL) | 8999 → 8000 | Log generator + streaming worker engine |
| `phantom_agent` | [mcp/agent/](mcp/agent/) + [bundles/spark/mcp/](bundles/spark/mcp/) | Next.js 15 + React 19, plus an embedded Python FastMCP subprocess | 3000 (UI), 8080 (MCP) | Chat UI, skills browser, model orchestration, ~80 MCP tools for Phantom, XSIAM (PAPI) and CALDERA |
| `caldera` | [bundles/spark/caldera-content/](bundles/spark/caldera-content/) content on a MITRE Caldera image | — | 8888 | Red-team operations backend |
| `phantom_browser` | [phantom-browser/](phantom-browser/) | headless Chromium | internal (CDP) | Browser for the `web` connector |
| `phantom-updater` | [updater/](updater/) | Python | internal | Per-instance connector container lifecycle (installer stack only) |

Connectors run as their own per-instance containers (see [`bundles/spark/connectors/CLAUDE.md`](bundles/spark/connectors/CLAUDE.md)). The MCP server is **embedded** in `phantom_agent`, not a separate service. Inside the compose network use service names (`http://xlog:8000`), not `localhost`.

## Running and testing

Docker (Compose v2) is the expected runtime; `docker-compose.yml` at the repo root builds the stack from source, and `installer/` produces the pinned-image install kit.

```bash
cp .env.example .env              # then fill in the keys you need
docker compose up -d --build
docker compose ps
docker compose logs -f phantom-agent
docker compose down

# Pre-deploy gate (run all four before pushing; see CLAUDE.md)
cd mcp/agent && npx tsc --noEmit && npm run lint && npm run build
cd ../../bundles/spark/mcp && PYTHONPATH=$PWD/src python3 -m pytest tests/ -x
```

`PYTHONPATH=$PWD/src` is required: many MCP tests import `usecase.*` from `src/`.

## Architecture that isn't obvious from the tree

- **xlog** mounts Strawberry GraphQL at `/` ([xlog/main.py](xlog/main.py), [xlog/app/schema.py](xlog/app/schema.py)). Log synthesis comes from the first-party `app/logforge/` engine. Format types, scenario shapes and worker I/O are declared in [xlog/app/types/](xlog/app/types/). The webhook sender uses header `Authorization: <WEBHOOK_KEY>` (raw, not `Bearer`). See [`xlog/CLAUDE.md`](xlog/CLAUDE.md) for worker lifecycle and the other gotchas.
- **Embedded MCP** ([bundles/spark/mcp/src/main.py](bundles/spark/mcp/src/main.py)) registers tools from `src/usecase/builtin_components/`; configuration goes through `src/config/config.py` (pydantic-settings), never raw `os.environ`. Connector tools are registered dynamically by `src/usecase/connector_loader.py`.
- **Skills library** is volume-seeded: edits to bundled skill files do not reach a running container's skills volume unless you reseed it (see [`mcp/agent/CLAUDE.md`](mcp/agent/CLAUDE.md) for the per-release marker and `FORCE_SKILLS_SYNC`).
- **Agent** authenticates MCP calls with `MCP_TOKEN`; `/api/agent/*` routes are thin proxies to the embedded MCP via `lib/mcp-proxy.ts`. Credentials are never exposed to the agent (see the credential guardrail in `CLAUDE.md`).

## Configuration

1. **[xlog/config.yml](xlog/config.yml)** is read by the log generator for worker count, log rotation and XSIAM parsed fields. Most keys are overridden by env vars.
2. **`.env`** at the repo root (copy from [`.env.example`](.env.example)) is the primary knob, loaded by `docker compose`. Never commit it. Critical keys: `MCP_TOKEN` (shared auth), the XSIAM PAPI trio (`CORTEX_MCP_PAPI_URL`, `CORTEX_MCP_PAPI_AUTH_HEADER`, `CORTEX_MCP_PAPI_AUTH_ID`), `CALDERA_*`, `WEBHOOK_ENDPOINT` / `WEBHOOK_KEY`, `TECHNOLOGY_STACK` (default log destination), and `SSL_CERT_PEM` / `SSL_KEY_PEM`.

## Conventions to preserve

- Adding an MCP tool: implement under `bundles/spark/mcp/src/usecase/builtin_components/`, register it in `src/main.py`, and check the credential guardrail in `CLAUDE.md` first (does it read or write a SecretStore value? then REST-only).
- Worker type enums, faker format enums and observable enums live in `xlog/app/types/`. New formats or destinations touch both the Strawberry enum and the dispatch in `xlog/app/schema.py`.
- The GraphQL endpoint is the single source of truth for log generation; the MCP layer reaches it through the `xlog` connector. Do not duplicate faker logic into the MCP layer.
