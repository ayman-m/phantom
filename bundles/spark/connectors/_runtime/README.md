# Phantom connector runtime contract — reference skeleton

> **Audience**: bundle authors writing a new Phantom connector for the
> container architecture. Read first; copy second.
>
> **See also**: `docs/spec-per-instance-connector-containers.md` for the
> architectural rationale.

A Phantom connector running under `runtimeMapping.style: container`
is, fundamentally, **a FastMCP server in a Docker container** with a
small handful of conventions. This directory shows the smallest
possible connector that satisfies the contract — `_runtime` (the
underscore prefix marks it as a reference, not a deployable connector;
the loader skips entries that start with `_`).

## The contract

A connector container MUST:

1. **Be `FROM phantom-connector-runtime:<version>`**. The base image
   provides FastMCP, the SecretStore reader, the InstanceStore reader,
   the audit forwarder, and the boot entrypoint. Don't reimplement
   any of those.

2. **Set `ENV CONNECTOR_ID=<id>`** matching the directory name and
   `connector.yaml`'s top-level `id:`. The runtime entrypoint reads
   this to find your source via `connectors.<id>.src.connector`.

3. **`COPY <bundle-path>/src /app/connectors/<id>/src`** so your
   Python module lives where the entrypoint expects to import it from.
   The build context is the repo root (build with
   `-f bundles/spark/connectors/<id>/Dockerfile .`).

4. **Define a `connector.py`** at `<bundle-path>/src/connector.py` that
   exposes your tool functions either via `__all__` (preferred — explicit)
   or as module-level public functions (fallback — the runtime auto-
   discovers them via module-scan).

5. **Function names follow one of these conventions**, which the
   runtime entrypoint normalizes to bare tool names:
     - `phantom_<id>_<tool>` → exposed as `<tool>`  (recommended for
       new connectors — namespace-clear for grep + audit)
     - `<id>_<tool>`         → exposed as `<tool>`  (legacy convention
       used by xsiam, caldera; both styles work)
     - `phantom_<tool>`      → exposed as `<tool>`  (legacy; single
       prefix without connector id)
     - `<tool>`              → exposed as `<tool>`  (no prefix; works
       but loses the audit-row breadcrumb that tells you which
       connector emitted the call)

6. **Use `from config.config import get_config`** to read per-instance
   configuration. The runtime's contextvar shim provides the same
   per-instance configuration API connector code has always used, so
   no connector-specific plumbing is needed.

7. **Connector-specific Python deps** go in your Dockerfile via
   `RUN pip install --no-cache-dir <dep1> <dep2>`. Don't touch the
   base image's requirements.txt — connector deps stay in the
   per-connector image so the base stays lean.

## What the runtime does FOR you

Things you do NOT need to implement in your connector:

- **FastMCP server boot** — runtime entrypoint starts it on port 9000.
- **Tool registration** — runtime walks your module's `__all__` (or
  module-scan fallback) and registers each function via `mcp.tool()`.
- **`/health` endpoint** — runtime adds it. Used by Docker healthcheck
  + phantom-updater readiness + agent-side proxy probes.
- **Per-instance config + secrets loading** — runtime reads your
  instance's row at boot, resolves secrets through the SecretStore,
  and stashes the merged dict on the contextvar for `get_config()`.
- **Audit forwarding** — `from runtime.audit_forwarder import record_event`
  works the same as the agent's `audit_log.record_event` did. The
  runtime POSTs back to the agent's `/api/v1/audit` endpoint.
- **SIGTERM handling** — runtime catches it, drains in-flight calls,
  and exits cleanly within Docker's 10s grace window.
- **Tool name prefix stripping** — `phantom_<id>_<tool>` becomes `<tool>`
  on the wire. The agent's MCP proxy adds the `<id>/` namespace
  prefix when forwarding calls.

## Files in this skeleton

```
_runtime/
├── README.md                      ← this file (the contract)
├── connector.yaml                 ← minimal manifest entry, style: container
├── Dockerfile                     ← FROM phantom-connector-runtime + COPY src
└── src/
    ├── __init__.py
    └── connector.py               ← one tool function as a starting point
```

The `_runtime/` is NOT registered in `bundles/spark/manifest.yaml`'s
`toolConnectors[]` — it's a reference, not a deployable connector.
To create a real connector, copy this directory to
`bundles/spark/connectors/<your-id>/`, replace `_runtime` with your
id throughout, add a `toolConnectors[]` entry to the manifest, and
add a per-connector image build to your build pipeline.

> **Connector ID naming constraint**: Docker rejects image-name
> segments that start with `_` or contain certain other characters.
> The `_runtime/` directory works as a Python package
> (underscore prefix is the Python convention for "private / skip"),
> but it cannot be built as `phantom-connector-_runtime:test` — Docker
> errors with "invalid reference format". Real connector ids must
> match `[a-z][a-z0-9-]*` (lowercase, alphanumeric + hyphens, starts
> with a letter). xlog, xsiam, caldera, web all comply; new
> connectors should pick names that comply too.

## Validation checklist before shipping a new connector

  - [ ] `connector.yaml` has `runtimeMapping.style: container`
  - [ ] `Dockerfile` is `FROM <registry>/phantom-connector-runtime-oss:<version>`
  - [ ] `Dockerfile` sets `ENV CONNECTOR_ID=<your-id>`
  - [ ] `src/connector.py` defines `__all__` listing your public tools
  - [ ] Function names follow one of the supported prefix conventions
  - [ ] Per-connector Python deps are pinned in your Dockerfile, NOT
        in `phantom-connector-runtime/requirements.txt`
  - [ ] Manifest's `toolConnectors[]` has your entry
  - [ ] The build pipeline builds the `phantom-connector-<id>` image
  - [ ] `docker build -f bundles/spark/connectors/<id>/Dockerfile .` succeeds
  - [ ] `docker run --rm --entrypoint python phantom-connector-<id>:test -c
         "import connectors.<id>.src.connector"` succeeds (no import errors)
