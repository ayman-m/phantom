# `bundles/spark/mcp/` — embedded Python MCP server

The Python FastMCP server that runs as a subprocess inside `phantom-agent`. Registers ~80 tools, exposes REST routes that the Next.js side proxies, talks to `xlog` + `caldera` + XSIAM PAPI.

**Repo-wide rules live in the [root CLAUDE.md](../../../CLAUDE.md)** — pre-deploy gate (incl. pytest), credential guardrail, contained-release discipline. This file holds only conventions LOCAL to the Python MCP server.

## Layout (clean-architecture flavor)

| Path | What it is |
|------|------------|
| `src/main.py` | Entry point. Registers ~80 tools in one block inside `async_main` — `mcp.tool()(module.fn)` per tool. |
| `src/config/config.py` | `pydantic-settings`, reads env vars via `validation_alias`. **Never** read `os.environ` directly. |
| `src/service/phantom_mcp/server.py` | FastMCP instance factory. |
| `src/usecase/builtin_components/` | Tool implementations. Each module groups related tools. |
| `src/usecase/connector_loader.py` | Dynamic registration of connector tools at boot. Holds `_BUILTIN_LEGACY_TOOLS` — the list of tools that are agent-callable. |
| `src/api/<resource>.py` | REST routes (the Next.js side proxies to these at `/api/v1/<resource>`). |
| `src/pkg/` | Shared clients — `graphql_client` (xlog), `papi_client` (XSIAM), `caldera_factory`, `xql_rag_service` (ChromaDB + sentence-transformers). |
| `tests/` | pytest suite (~421 tests). |
| `skills/` | Default skills baked into the agent image at `/app/mcp/skills-default/`; volume-seeded to `/app/skills/` at boot (see [`../../../mcp/agent/CLAUDE.md`](../../../mcp/agent/CLAUDE.md) § Skills bootstrap). |

## Transports

- `streamable-http` is the only mode in the embedded form.
- HTTP path is configurable via `MCP_PATH` (default `/api/v1/stream/mcp`).
- TLS terminated by the agent's `tls-proxy.js` sidecar — the MCP itself listens plain HTTP on loopback 8080.

## Tool registration conventions

When adding an MCP tool:
1. Implement under `src/usecase/builtin_components/<module>.py`.
2. Register in `src/main.py` with `mcp.tool()(<module>.<fn>)`.
3. Config goes through `src/config/config.py` (pydantic-settings with `validation_alias`), NOT raw `os.environ`.
4. Write a docstring with an **Args section** + a **concrete example payload** — the agent picks fields by reading the docstring, not just the signature. See root § Documentation discipline rule 9.
5. **Credential guardrail check** (root § Agent credential guardrail): does this tool read or write a SecretStore value? If yes → REST-only (`src/api/<resource>.py`), never `mcp.tool()`-registered. The agent never gets a handle to credentials.
6. **Catalog boundary check** (root § Catalog boundary ≠ credential boundary): does this tool mutate catalog metadata (install state, schema, registry membership)? If yes AND #5 is no → safe to `mcp.tool()`-register.

## Pytest

```bash
cd bundles/spark/mcp
PYTHONPATH=$PWD/src python3 -m pytest tests/ -x   # ~7-8s, ~421 tests
```

**`PYTHONPATH=$PWD/src` is REQUIRED.** Half the test files use `from usecase.X import Y`; they fail to import without `src/` on the path. CI sets it via `PYTHONPATH=/work/bundles/spark/mcp/src`.

## Bug-family audit

When fixing a bug here, audit sibling files for the same bug pattern in the same release. The blast radius of an MCP-internal bug rarely stops at one file — usually a code pattern copy-pasted across `builtin_components/` modules or shared via `connector_loader.py`. Procedure:
1. Identify the bug as a `grep` expression.
2. Run it across `src/usecase/` + `src/api/` + `bundles/spark/connectors/*/src/`.
3. For each hit, fix it OR document the gap inline with a tracking-issue reference. Never silently leave a known-broken sibling.

## Worker enums + GraphQL source-of-truth (xlog interaction)

The GraphQL endpoint at `xlog` (port 8000) is the **single source of truth** for log generation. The MCP reaches it through the `xlog` connector. Do NOT duplicate faker logic into the MCP layer — call xlog instead. Worker type / faker format / observable enums are defined in `xlog/app/types/` (Strawberry); the MCP receives them in responses.

See [`../../../xlog/CLAUDE.md`](../../../xlog/CLAUDE.md) for the GraphQL side.
