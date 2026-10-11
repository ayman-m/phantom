"""Runtime entrypoint for per-instance connector containers.

Boot sequence (read top-to-bottom, executed in order):

    1. Read env vars:
         CONNECTOR_ID  — which connector to load (e.g. "xlog")
         INSTANCE_ID   — which instance row to look up
         DATA_ROOT     — host path of the agent's data dir
                         (default /app/data, mounted ro)
         PORT          — FastMCP HTTP port (default 9000)
         PHANTOM_SECRET_KEK   — AES-256-GCM key (env-inherited)
         PHANTOM_AUDIT_URL    — agent audit endpoint (optional)
         MCP_TOKEN            — bearer for the audit endpoint (optional)

    2. Read the instance row from instances.db.

    3. Resolve the instance's secret_refs through the SecretStore,
       merge into a single overrides dict.

    4. Set the contextvar (via config.config.set_current_instance) so
       connector code's `from config.config import get_config` returns
       this instance's values.

    5. Import the connector module: `connectors.<CONNECTOR_ID>.src.connector`.
       The module's top-level `__all__` enumerates the tool functions
       to register.

    6. Build a FastMCP server, register each tool function from the
       connector module, and add a `/health` HTTP endpoint via
       custom_route.

    7. Start the audit forwarder background task.

    8. Run uvicorn on PORT until SIGTERM.

# What this entrypoint does NOT do (intentionally)

  - Does NOT load the bundle's manifest.yaml. Manifest-level
    decisions (humanRequired, tools.allow/deny) are enforced
    agent-side; the connector container only executes tool calls
    that the agent's MCP proxy decided to route here.

  - Does NOT do per-call instance switching. One container = one
    instance, fixed at boot. To run two instances of the same
    connector, the operator creates two instances → phantom-updater
    starts two containers.

  - Does NOT speak directly to Vertex / external embed APIs. Memory
    + KB are agent-side concerns; connectors are stateless from
    that perspective.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

import uvicorn
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

# Runtime helpers (siblings in the runtime package).
from runtime.audit_forwarder import init_forwarder
from runtime.instance_store_client import (
    InstanceStoreClientError,
    InstanceStoreReader,
)
from runtime.secret_store_client import (
    SecretStoreClientError,
    SecretStoreReader,
)

# Config shim. Setting the contextvar BEFORE the connector module
# imports means any module-level get_config() call in the connector
# also sees the instance values (today's connectors only call it at
# tool-call time, but defensive).
from config.config import set_current_instance


logger = logging.getLogger("connector-runtime")


def _setup_logging() -> None:
    """Standard logging — INFO to stderr, prefixed for log aggregation
    (`docker logs phantom-connector-X` is the consumer)."""
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stderr,
    )


def _read_env_or_fail() -> dict[str, str]:
    """Read required env vars, fail loudly if any are missing.

    Required: CONNECTOR_ID, INSTANCE_ID. The rest have defaults
    or are optional (audit URL, MCP_TOKEN).
    """
    required = ("CONNECTOR_ID", "INSTANCE_ID")
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        logger.error(
            "missing required env vars: %s. Set them via phantom-updater's "
            "container start payload — see docs/spec-per-instance-connector-"
            "containers.md §D5.",
            ", ".join(missing),
        )
        sys.exit(2)
    return {
        "connector_id": os.environ["CONNECTOR_ID"],
        "instance_id": os.environ["INSTANCE_ID"],
        "data_root": os.getenv("DATA_ROOT", "/app/data"),
        "port": os.getenv("PORT", "9000"),
    }


def _load_instance(env: dict[str, str]) -> dict[str, Any]:
    """Read instance row + resolve secrets → flat overrides dict.

    Errors here are fatal (exit 3): without instance config, the
    connector can't function. phantom-updater's restart policy will
    retry a few times in case the instance row was being created
    concurrently with container start.
    """
    data_root = Path(env["data_root"])
    db_path = data_root / "instances.db"

    try:
        ireader = InstanceStoreReader(db_path)
        instance = ireader.get(env["instance_id"])
        sreader = SecretStoreReader(data_root)
        merged = ireader.resolve_merged_config(instance, sreader)
    except (InstanceStoreClientError, SecretStoreClientError) as exc:
        logger.error(
            "failed to load instance %s/%s from %s: %s",
            env["connector_id"], env["instance_id"], data_root, exc,
        )
        sys.exit(3)

    logger.info(
        "loaded instance %s/%s (%d config keys, %d secret slots resolved)",
        instance.connector_id, instance.name,
        len(instance.config), len(instance.secret_refs),
    )
    return merged


def _import_connector_module(connector_id: str) -> Any:
    """Import the connector's source module from the per-connector image.

    The per-connector Dockerfile is expected to:
      1. Be `FROM phantom-connector-runtime:<version>`
      2. COPY its `bundles/spark/connectors/<id>/src/` into
         `/app/connectors/<id>/src/`
      3. Set `CONNECTOR_ID=<id>`

    With `PYTHONPATH=/app` (set by the runtime Dockerfile), this
    import resolves to `/app/connectors/<id>/src/connector.py`. The
    module's top-level `__all__` enumerates which functions to
    register as tools.
    """
    module_path = f"connectors.{connector_id}.src.connector"
    try:
        mod = importlib.import_module(module_path)
    except ImportError as exc:
        logger.error(
            "could not import connector module %r: %s. "
            "Verify the per-connector image COPYed src/ to "
            "/app/connectors/%s/src/.",
            module_path, exc, connector_id,
        )
        sys.exit(4)
    return mod


def _register_tools(
    mcp: FastMCP, connector_module: Any, connector_id: str
) -> int:
    """Register every callable in `connector_module.__all__` as a
    FastMCP tool. Returns the number registered."""
    names: list[str] = list(getattr(connector_module, "__all__", []) or [])
    if not names:
        # Fall back: register every public FUNCTION defined directly
        # on the module. Filter to functions/coroutines specifically —
        # Pydantic Request classes (which xsiam/caldera define for
        # tool argument schemas) are also callable + defined in the
        # same module, but they're NOT tools. Including them would
        # advertise garbage like `RunXqlQueryRequest` as a tool name.
        #
        # Without this filter the fallback picks up the Pydantic models
        # as well as the real tools (e.g. 27 names instead of 15 for xsiam).
        # Filtering with isfunction + iscoroutinefunction trims to just the
        # real tools.
        names = [
            n for n, val in vars(connector_module).items()
            if not n.startswith("_")
            and (
                inspect.isfunction(val)
                or inspect.iscoroutinefunction(val)
            )
            and inspect.getmodule(val) is connector_module
        ]
        logger.warning(
            "connector %r has no __all__ — falling back to %d public "
            "functions auto-discovered. Define __all__ for stable "
            "tool registration.",
            connector_id, len(names),
        )

    # Compute an additional prefix to strip based on what's actually
    # common across the tool names.
    #
    # Why: a connector's functions may use the functionPrefix from
    # connector.yaml (e.g. cortex-xdr's `xdr_`, cortex-docs' `cortex_`),
    # which none of the fixed strip rules below (`phantom_<connector_id>_`,
    # `<connector_id>_`, `phantom_`) match. Without a match the runtime
    # would register `xdr_get_cases_and_issues`, while the agent's proxy
    # always calls the bare name from connector.yaml spec.tools[].name
    # (`get_cases_and_issues`) and gets "Unknown tool".
    #
    # So: auto-detect the longest common prefix among the tool names
    # AND add it as a strip rule (with the lowest priority — only
    # used if the existing rules don't match). Conservative:
    #   - Only applies when ≥2 names are being registered (a single-
    #     tool connector has no "common" prefix to detect).
    #   - Common prefix must end in `_` (we're stripping namespace
    #     prefixes, not arbitrary string prefixes).
    #   - Common prefix length must be ≥3 chars to avoid stripping
    #     accidental shared starts (e.g. `get_` across all 3 GET tools).
    common_prefix = ""
    if len(names) >= 2:
        # Longest common prefix via reduce. Python's os.path.commonprefix
        # works on strings too.
        from os.path import commonprefix
        candidate = commonprefix(names)
        # Trim back to the last `_` so we don't slice mid-word.
        last_underscore = candidate.rfind("_")
        if last_underscore > 0:
            candidate = candidate[: last_underscore + 1]
            # Don't double-strip prefixes the existing rules already
            # handle. Same length-3 sanity check.
            if (
                len(candidate) >= 3
                and candidate != f"{connector_id}_"
                and candidate != f"phantom_{connector_id}_"
                and candidate != "phantom_"
            ):
                common_prefix = candidate
                logger.info(
                    "connector %r: auto-detected common tool-name prefix %r; "
                    "added to strip rules. (supports connectors whose "
                    "functionPrefix doesn't match <connector_id>_ or "
                    "phantom_ patterns.)",
                    connector_id, common_prefix,
                )

    registered = 0
    for name in names:
        fn = getattr(connector_module, name, None)
        if fn is None or not callable(fn):
            logger.warning(
                "connector %r: __all__ references %r but it isn't "
                "callable; skipping.",
                connector_id, name,
            )
            continue
        # Strip the legacy function-name prefix before exposing the
        # tool name. The agent's MCP proxy routes by bare tool name
        # (`navigate`, `create_data_worker`, `run_xql_query`, etc.);
        # the prefix was an in-process namespace trick that the
        # container provides by construction.
        #
        # Four prefix forms checked:
        #   - `phantom_<id>_*`  → xlog uses `phantom_create_data_worker`
        #                          and `phantom_web_navigate` (web has
        #                          its own `phantom_web_` prefix). Most
        #                          specific; check first.
        #   - `<id>_*`          → xsiam uses `xsiam_run_xql_query`,
        #                          caldera uses `caldera_health_check`.
        #   - `phantom_*`       → bare phantom_ prefix (legacy).
        #   - `<common_prefix>` → auto-detected longest
        #                          common prefix ending in `_`. Catches
        #                          cortex-docs (`cortex_*`) and any
        #                          future connector whose functionPrefix
        #                          doesn't match the connector_id stem.
        # Order matters: more-specific prefixes tested first so we
        # don't strip too little (e.g. `phantom_xlog_navigate` should
        # become `navigate`, not `xlog_navigate`).
        tool_name = name
        for prefix in (
            f"phantom_{connector_id}_",
            f"{connector_id}_",
            "phantom_",
            common_prefix,  # auto-detected; "" when not applicable (skip)
        ):
            if prefix and tool_name.startswith(prefix):
                tool_name = tool_name[len(prefix):]
                break
        mcp.tool(name=tool_name)(fn)
        registered += 1
        logger.debug("registered tool %s/%s → %s", connector_id, tool_name, name)
    logger.info(
        "registered %d tool(s) for connector %r", registered, connector_id,
    )
    return registered


def _build_app(mcp: FastMCP, port: int) -> Any:
    """Wire FastMCP's HTTP transport + add the /health endpoint that
    Docker healthcheck + phantom-updater readiness use."""
    # FastMCP's http_app() returns a Starlette app with the MCP
    # endpoint mounted. We add /health on top.
    app = mcp.http_app(path="/mcp", transport="streamable-http")

    async def health(_request: Request) -> JSONResponse:
        # Simple "I'm alive" response; for the basic Docker healthcheck,
        # alive-is-ready (no separate "instance loaded + tools registered"
        # check).
        return JSONResponse({"status": "ok"})

    app.add_route("/health", health, methods=["GET"])
    return app


async def _async_main() -> None:
    _setup_logging()
    env = _read_env_or_fail()
    logger.info(
        "starting phantom-connector-runtime: connector=%s instance=%s port=%s",
        env["connector_id"], env["instance_id"], env["port"],
    )

    # Load instance config + secrets, stash on the contextvar.
    overrides = _load_instance(env)
    set_current_instance(overrides)

    # Audit forwarder background task.
    forwarder = init_forwarder()
    await forwarder.start()

    # Import the connector + register its tools.
    connector_module = _import_connector_module(env["connector_id"])
    mcp = FastMCP(name=f"phantom-connector-{env['connector_id']}")
    n_registered = _register_tools(mcp, connector_module, env["connector_id"])
    if n_registered == 0:
        logger.error(
            "connector %r registered zero tools — refusing to start. "
            "Check the connector module's __all__ list.",
            env["connector_id"],
        )
        sys.exit(5)

    # Build the Starlette app + uvicorn config. Bind 0.0.0.0 so the
    # agent's MCP (in another container on the same compose network)
    # can reach us.
    port = int(env["port"])
    app = _build_app(mcp, port)
    config = uvicorn.Config(
        app=app, host="0.0.0.0", port=port,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
        access_log=False,
    )
    server = uvicorn.Server(config)

    # SIGTERM handler — drain audit forwarder, ask uvicorn to exit.
    # Docker stop sends SIGTERM with a 10s grace period before SIGKILL.
    loop = asyncio.get_event_loop()
    stop_evt = asyncio.Event()

    def _on_sigterm() -> None:
        logger.info("received SIGTERM — draining + shutting down")
        stop_evt.set()
        server.should_exit = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _on_sigterm)

    try:
        await server.serve()
    finally:
        await forwarder.stop()
        logger.info("connector container exited cleanly")


def main() -> None:
    """Synchronous entrypoint that asyncio.run wraps the async logic.
    Configured as the Dockerfile's ENTRYPOINT module."""
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
