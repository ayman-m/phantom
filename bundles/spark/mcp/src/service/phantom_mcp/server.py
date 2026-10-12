"""MCP Server creation and lifecycle management."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger("Phantom MCP")


def create_mcp_lifespan():
    """
    Factory function to create mcp_lifespan.

    The xlog URL is resolved by a function that
    reads the active xlog instance's baseUrl from the InstanceStore
    on every invocation, rather than being pinned to a single
    env-driven URL at MCP boot. Operators edit baseUrl via /connectors and
    the next tool call sees the new value with no MCP restart.
    Single source of truth: `instance.config.baseUrl` for the xlog
    instance kept in the InstanceStore.

    The resolver looks up `get_instance_store()` lazily because
    create_mcp_server is called BEFORE the InstanceStore is wired
    (main.py creates the MCP first, then registers the store via
    set_instance_store). Late binding keeps the order working.
    """

    @asynccontextmanager
    async def mcp_lifespan(mcp_server: FastMCP) -> AsyncIterator[dict]:
        def get_xlog_url() -> str:
            # Late-bind: import inside the function so we don't depend
            # on import order between server.py and instance_store.py.
            # The getter in instance_store.py is named `instance_store`
            # (not `get_instance_store`) — see usecase/instance_store.py
            # bottom of file.
            try:
                from usecase.instance_store import instance_store as get_store
                store = get_store()
            except Exception as exc:
                logger.warning("instance_store() lookup failed: %s", exc)
                store = None

            if store is not None:
                try:
                    instances = store.list_for("xlog")
                except Exception as exc:
                    logger.warning(
                        "InstanceStore.list_for('xlog') failed: %s",
                        exc,
                    )
                    instances = []
                if instances:
                    cfg = instances[0].config or {}
                    # The config field may be stored as `baseUrl`, `xlogUrl`
                    # (camelCase; the marketplace catalog declares the
                    # field under that name while connector.yaml's schema
                    # says `baseUrl`), `xlog_url` (snake) or `url`, so
                    # the fallback chain accepts all four.
                    base = (
                        cfg.get("baseUrl")
                        or cfg.get("xlogUrl")
                        or cfg.get("xlog_url")
                        or cfg.get("url")
                    )
                    if isinstance(base, str) and base.strip():
                        return base.strip().rstrip("/")

            raise RuntimeError(
                "No xlog instance configured. Add a primary-xlog "
                "instance via /connectors and set its baseUrl."
            )

        try:
            logger.info("Initializing Phantom MCP Server...")
            context = {
                # Tool handlers call get_xlog_url() each time they need
                # the URL. Single source of truth: InstanceStore's
                # primary-xlog instance.config.baseUrl. /connectors
                # edits propagate immediately, no MCP restart needed.
                "get_xlog_url": get_xlog_url,
            }
            logger.info("Phantom MCP Server initialized successfully")
            yield context
        except Exception as e:
            logger.exception(f"Error during MCP server initialization: {e}")
            raise

    return mcp_lifespan


def create_mcp_server() -> FastMCP:
    """Create FastMCP server. xlog URL is resolved lazily from the
    InstanceStore at each tool call — see create_mcp_lifespan."""
    lifespan = create_mcp_lifespan()

    mcp = FastMCP(
        name="Phantom MCP Server",
        instructions="""
# Phantom MCP Server - Security Testing & Simulation Platform

You are connected to the Phantom MCP Server, a comprehensive security testing and simulation platform that enables:

## Core Capabilities

### 1. Synthetic Log Generation (ARB CISD Standard - 46 Data Sources)
- Generate realistic security logs for **46 different data sources** across **6 domains**:
  - Operating System (7): Windows Server, Active Directory, Workstations, Exchange, Sysmon, Linux/Unix, AIX
  - Network & Infrastructure (14): Load Balancer, Middleware, File Share, DNS, DHCP, Switches, Routers, etc.
  - Security Controls (11): EDR, CSPM, Email Gateway, FIM, DLP, PAM, MDM, XSOAR, Threat Intel, Vuln Mgmt, EPP
  - Network Security (9): NDR, TLS Inspection, DDoS Protection, NGFW, IPS/IDS, VPN, WLC, Proxy, NAC
  - Database (2): Database Engine (RDBMS), Database Security Control (DAM)
  - Applications (3): API Gateway, WAF, Custom Applications

- Support multiple formats (SYSLOG, CEF, LEEF, WINEVENT, JSON)
- Create continuous log streams with customizable intervals and observables
- Send logs to various destinations (UDP, TCP, HTTPS, XSIAM, Webhooks)
- Simulate attack scenarios following MITRE ATT&CK framework

### 2. CALDERA Attack Simulation Integration
- Full CALDERA C2 framework control for adversary emulation
- Manage abilities (atomic attack techniques) mapped to MITRE ATT&CK
- Create and execute operations with adversary profiles
- Track execution with links, facts, and relationship graphs
- Generate comprehensive attack reports and telemetry

### 3. XSIAM (Cortex) Security Platform Integration
- Execute XQL queries for threat hunting and investigation
- Manage security cases, assets, and issues
- Interact with lookup tables for enrichment data
- Send logs via HTTP collectors (webhooks)
- Access datasets and field information
- AI-powered XQL query assistance with RAG

## Vendor & Product Standards

**CRITICAL**: Always use realistic vendor/product names from the Device Vendor Catalog:
- ✅ Use specific vendors: Palo Alto, CrowdStrike, Microsoft, Cisco, F5, Proofpoint, etc.
- ❌ NEVER use: "Phantom", "Generic", "Unknown", or made-up names
- ✅ Create variety: Use different vendors for different logs (e.g., Palo Alto for perimeter firewall, Fortinet for branch firewall)
- ✅ Match vendors to context: Azure for cloud, Cisco for data center, CrowdStrike for EDR, Proofpoint for email

**Format-Specific Requirements:**
- **JSON** (XSIAM): Azure, Corelight, Zscaler, Symantec, Akamai, CrowdStrike, Kong, AWS, Okta, HashiCorp
- **CEF**: Palo Alto, Cisco, F5, Imperva, Fortinet, Check Point, Suricata
- **LEEF**: Proofpoint, Mimecast, Zscaler
- **SYSLOG**: Cisco, Infoblox, Pulse Secure, Red Hat, IBM, Juniper, Arista, Apache, Nginx
- **WINEVENT**: Microsoft (no vendor/product field needed - use srcHost in observables)

## Common Use Cases

**Security Testing**: Test SIEM ingestion, parsing rules, and correlation logic with realistic synthetic data from all 46 data sources

**Red Team Exercises**: Execute end-to-end attack simulations using CALDERA and capture telemetry from multiple security controls

**Detection Engineering**: Generate attack scenarios to validate detection rules across different vendor products

**Training & Education**: Create realistic security incidents for SOC analyst training with industry-standard vendor logs

**Performance Testing**: Test log processing pipelines with high-volume synthetic data streams from diverse sources

## Best Practices

1. **Start with CALDERA health check** before running operations
2. **Create workers for continuous log generation**, use scenarios for attack sequences
3. **Use Device Vendor Catalog** (skills/foundation/DEVICE_VENDOR_CATALOG.md) for vendor selection
4. **Use XSIAM queries** to validate that generated logs are being ingested correctly
5. **Track CALDERA operations** through their full lifecycle: create → start → monitor → report
6. **Build knowledge graphs** using facts and relationships from CALDERA operations
7. **Generate variety**: Use different vendors for different devices in the same exercise

## Important Notes

- CALDERA operations start in "paused" state - update state to "running" to execute
- Workers stream logs continuously until stopped - monitor and stop when done
- XSIAM webhooks require proper authentication (WEBHOOK_ENDPOINT and WEBHOOK_KEY)
- Use observables_dict to control specific field values in generated logs
- Link execution status: 0=success, -1=running, -2=discarded
- Network devices REQUIRE network fields: localIp, remoteIp, sourcePort, remotePort, protocol

Always verify connectivity to backend services (Phantom, CALDERA, XSIAM) before starting operations.
""",
        lifespan=lifespan,
    )

    @mcp.custom_route("/ping/", methods=["GET"], include_in_schema=False)
    async def _health_check_route(request: Request) -> JSONResponse:
        """Liveness + lightweight readiness probe.

        Returns:
            status:        "ok" — process is up
            embedder_mode: "vertex" | "stub". "stub" means search returns
                           hash-similarity scores, NOT semantic matches;
                           the UI should show a degradation badge until a
                           Vertex provider is saved on /providers. The env
                           var PHANTOM_EMBEDDER_MODE is stamped at boot and
                           re-stamped by EmbedderRuntime.refresh() whenever a
                           Vertex provider is saved, so this read is cheap
                           and current (a module-global would race the
                           worker context this handler runs in).
        """
        import os
        return JSONResponse(
            {
                "status": "ok",
                "embedder_mode": os.environ.get("PHANTOM_EMBEDDER_MODE", "unknown"),
            },
        )

    return mcp
