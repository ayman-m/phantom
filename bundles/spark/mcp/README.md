# Embedded MCP server (Phantom v1.2 bundle)

This directory IS the embedded MCP runtime — Dockerfile, Python
source, dependencies, and entrypoint all live here. The
`phantom-mcp` Docker service builds from this directory and runs as
the agent's tool surface.

## Layout

```
bundles/spark/mcp/
├── Dockerfile              # python:3.12-slim base + COPY src/ /app/src/
├── requirements.txt        # MCP runtime deps (fastmcp, pyyaml, sqlalchemy, …)
├── entrypoint.sh           # seeds /app/skills from /app/skills-default; runs main.py
├── run.sh                  # local-dev launcher (skip docker)
├── server.yaml             # bundle metadata declaration (per spec §7.4)
├── src/
│   ├── main.py             # entrypoint: build FastMCP, register tools+routes, serve
│   ├── config/config.py    # pydantic Settings + per-call contextvar proxy (stage 3A)
│   ├── api/
│   │   ├── auth.py         # Bearer-token gate for admin endpoints
│   │   └── instances.py    # POST/GET/DELETE /api/v1/instances
│   ├── usecase/
│   │   ├── connector_loader.py  # reads bundle, gates tools on instances, wraps with contextvar
│   │   ├── instance_store.py    # sqlite-backed CRUD over data_root/instances.db
│   │   └── builtin_components/  # runtime built-ins (skills_*, simulation_skills)
│   ├── service/phantom_mcp/server.py  # FastMCP instance factory
│   ├── pkg/setup_logging.py # shared infra (logging only)
│   └── entities/mcp_context.py # shared types
├── resources/              # bundled XQL doc + examples
├── skills/                 # default skills seeded into /app/skills volume
└── tests/                  # pytest suite
```

## Runtime contract

At boot, `main.py`:

1. Constructs the FastMCP server (`service/phantom_mcp/server.py`)
2. Mounts the admin HTTP API (`api/instances.py` and the other routers under `api/`)
3. Calls `connector_loader.iter_registrations()`:
   - Reads `/app/bundle/manifest.yaml` → `toolConnectors[]`
   - For each connector: reads `connector.yaml`, resolves
     `runtimeMapping` (style + functionPrefix), imports the source
     from `/app/bundle/connectors/<id>/src/`
   - Reads instances from `data_root/instances.db` (gating: a
     connector with no instance gets none of its tools advertised)
   - Auto-migrates env-var-driven default instances on first boot
   - Wraps each tool's callable in a contextvar that injects the
     instance's config + secrets at call time
4. Registers all yielded tools on the FastMCP instance
5. Starts the streamable-HTTP server on `:8080`

## Bundle paths the runtime expects

The Docker image bind-mounts these from the bundle root:

| Path in image | Bound from | Purpose |
|---|---|---|
| `/app/bundle/manifest.yaml` | `bundles/spark/manifest.yaml` | toolConnectors[] + setup.bindsInstances[] |
| `/app/bundle/connectors/<id>/connector.yaml` | bundle | tool catalog + runtimeMapping |
| `/app/bundle/connectors/<id>/src/` | bundle | connector implementations |
| `/app/data/instances.db` | `phantom_mcp_data` volume | sqlite instance store |
| `/app/skills/` | `phantom_mcp_skills` volume | runtime-mutable skills (seeded from `skills-default/`) |

## Spark-platform mode (stage 3E — coming)

When `SPARK_PLATFORM_GATEWAY` is set in the environment, this
runtime will **not** spawn its embedded MCP — the platform's central
`connector-manager` MCP supersedes it. Connector source from this
bundle gets pushed to the workspace marketplace via
`gateway.PublishConnector`, gated on admin approval, then registered
with `connector-manager`. Same connector.yaml artifacts; same tool
namespaces.
