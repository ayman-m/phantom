"""Plugin entry-point HTTP endpoints.

Distinct from `api/plugins.py` which handles the filesystem-discovered
plugin system (`bundles/spark/plugins/<vendor>/`). This module
serves the DISTRIBUTABLE plugin system (`plugin_entry_points.py` walking `importlib.metadata.entry_points` for
pip-installable Python packages).

  GET    /api/v1/plugin-entries           list (groups + total)
  POST   /api/v1/plugin-entries/install   pip install --user <spec>
  DELETE /api/v1/plugin-entries/{dist}    pip uninstall -y <dist>
"""

from __future__ import annotations

import asyncio
import logging
import sys

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import require_bearer

logger = logging.getLogger("Phantom MCP")


def register_plugin_entry_points_routes(mcp: FastMCP) -> None:
    @mcp.custom_route(
        "/api/v1/plugin-entries", methods=["GET"], include_in_schema=False,
    )
    async def list_entries(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            from usecase.plugin_entry_points import discover_all
            groups = discover_all()
        except Exception as exc:
            logger.warning("plugin-entries discovery failed: %s", exc)
            return JSONResponse(
                {"error": f"discovery failed: {exc}", "groups": {}, "total": 0},
                status_code=500,
            )
        out_groups = {g: [r.to_dict() for r in refs] for g, refs in groups.items()}
        total = sum(len(refs) for refs in groups.values())
        return JSONResponse({"groups": out_groups, "total": total})

    @mcp.custom_route(
        "/api/v1/plugin-entries/install",
        methods=["POST"],
        include_in_schema=False,
    )
    async def install_entry(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "body must be JSON"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse(
                {"error": "body must be a JSON object"}, status_code=400
            )
        spec = body.get("spec")
        if not isinstance(spec, str) or not spec.strip():
            return JSONResponse(
                {"error": "'spec' is required (non-empty string)"},
                status_code=400,
            )
        spec = spec.strip()
        if any(ch in spec for ch in (";", "|", "&", "$", "`", "\n", "\r")):
            return JSONResponse(
                {"error": "spec contains disallowed shell characters"},
                status_code=400,
            )
        logger.info("plugin-entries install: %s", spec)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", "--user",
            "--disable-pip-version-check", "--quiet", spec,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out_b, err_b = await proc.communicate()
        out = out_b.decode("utf-8", errors="replace")
        err = err_b.decode("utf-8", errors="replace")
        rc = proc.returncode
        try:
            from usecase.audit_log import record_event
            record_event(
                "plugin_install",
                target=f"plugin:{spec[:120]}",
                status="success" if rc == 0 else "failure",
                metadata={"spec": spec, "return_code": rc, "stderr_tail": err[-500:]},
            )
        except Exception:
            pass
        if rc != 0:
            return JSONResponse(
                {"error": "pip install failed", "return_code": rc,
                 "stderr": err[-1500:], "stdout": out[-1500:]},
                status_code=500,
            )
        try:
            from usecase.plugin_entry_points import discover_all
            groups = discover_all()
            counts = {g: len(refs) for g, refs in groups.items()}
        except Exception as exc:
            counts = {}
            logger.warning("post-install discovery failed: %s", exc)
        # Clear the plugin-hook handler cache so the next
        # /api/v1/plugin-hooks call re-walks entry-points and picks
        # up newly-installed handlers without an MCP restart.
        try:
            from usecase.plugin_hook_runner import clear_cache
            clear_cache()
        except Exception:
            pass
        return JSONResponse(
            {
                "ok": True, "spec": spec, "stdout_tail": out[-500:],
                "discovery_counts": counts,
                "note": (
                    "Newly-discovered entry-points visible at "
                    "GET /api/v1/plugin-entries. The "
                    "agent's hook-runner can also INVOKE plugin-"
                    "contributed handlers in the phantom.hooks group "
                    "via the 'plugin' transport in /settings/hooks. "
                    "Other contribution types (skills, connectors, "
                    "scanners, providers) still need a phantom-agent "
                    "restart to land."
                ),
            },
            status_code=201,
        )

    @mcp.custom_route(
        "/api/v1/plugin-entries/{dist_name}",
        methods=["DELETE"],
        include_in_schema=False,
    )
    async def uninstall_entry(request: Request) -> JSONResponse:
        if (resp := require_bearer(request)) is not None:
            return resp
        dist_name = request.path_params["dist_name"]
        if any(ch in dist_name for ch in (";", "|", "&", "$", "`", "/", "\n", "\r", " ")):
            return JSONResponse(
                {"error": "dist_name contains disallowed characters"},
                status_code=400,
            )
        if not dist_name.strip():
            return JSONResponse({"error": "dist_name is required"}, status_code=400)
        logger.info("plugin-entries uninstall: %s", dist_name)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "uninstall", "-y",
            "--disable-pip-version-check", dist_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out_b, err_b = await proc.communicate()
        out = out_b.decode("utf-8", errors="replace")
        err = err_b.decode("utf-8", errors="replace")
        rc = proc.returncode
        try:
            from usecase.audit_log import record_event
            record_event(
                "plugin_uninstall",
                target=f"plugin:{dist_name}",
                status="success" if rc == 0 else "failure",
                metadata={
                    "dist_name": dist_name, "return_code": rc,
                    "stderr_tail": err[-500:],
                },
            )
        except Exception:
            pass
        if rc != 0:
            return JSONResponse(
                {"error": "pip uninstall failed", "return_code": rc,
                 "stderr": err[-1500:], "stdout": out[-1500:]},
                status_code=500,
            )
        # Clear plugin-hook handler cache. Skill/connector/
        # provider/scanner caches still require a phantom-agent
        # restart since those registries don't yet hot-reload.
        try:
            from usecase.plugin_hook_runner import clear_cache
            clear_cache()
        except Exception:
            pass
        return JSONResponse(
            {
                "ok": True, "dist_name": dist_name, "stdout_tail": out[-500:],
                "note": (
                    "Plugin-hook handler cache flushed. For other "
                    "contribution types (skills, connectors, providers, "
                    "scanners), restart phantom-agent to fully purge."
                ),
            }
        )
