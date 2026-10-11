# phantom-connector-runtime — base image for per-instance connector
# containers (see docs/spec-per-instance-connector-containers.md).
#
# Every per-connector image (phantom-connector-xlog, -xsiam, -caldera,
# -web) inherits from this base, adds its own connector source +
# connector-specific deps, and inherits the entrypoint defined here.
#
# # What lives here:
#   - FastMCP (the MCP server the agent's proxy talks to)
#   - SecretStore reader (decrypts per-instance secrets at boot)
#   - InstanceStore reader (looks up the instance's config row)
#   - Audit forwarder (POSTs durable audit events to the agent)
#   - Config-shim (mimics phantom-agent's config.config.get_config()
#     interface so connector code that imports it works unchanged)
#   - Runtime entrypoint (boots, loads instance config + secrets,
#     imports the connector module, registers tools, starts FastMCP)
#
# # What the per-connector image must add:
#   - Connector source at /app/connectors/<id>/src/
#   - CONNECTOR_ID env var defaulted to <id>
#   - Optional: connector-specific deps via its own pip install
#
# # Why python:3.12-slim:
# Same major+minor as phantom-agent's MCP base. Keeps the Python
# version aligned across the agent process and connector containers,
# so any dependency that was tested in phantom-agent works here.
# Slim variant trims ~200 MB of build tools we don't need at runtime.

# Pinned by digest. Update via:
#   docker pull python:3.12-slim && \
#     docker inspect --format='{{index .RepoDigests 0}}' python:3.12-slim
# This image is the FROM for every per-connector container, so a
# digest move here cascades to all 6 connector images on the next
# release. Pinning makes that cascade deliberate, not accidental.
FROM python:3.12-slim@sha256:401f6e1a67dad31a1bd78e9ad22d0ee0a3b52154e6bd30e90be696bb6a3d7461

LABEL org.opencontainers.image.source="https://github.com/ayman-m/phantom"
LABEL org.opencontainers.image.description="Phantom connector runtime base — FastMCP + SecretStore + audit forwarder. Each per-connector image inherits this and adds its own source + deps."
LABEL org.opencontainers.image.licenses="Apache-2.0"

WORKDIR /app

# Install runtime deps. --no-cache-dir keeps the image lean; pip's
# wheel cache adds ~50 MB that we'd never reuse at runtime.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r /app/requirements.txt

# Copy the runtime library + config shim. PYTHONPATH=/app exposes
# both `runtime.*` (the runtime infra) and `config.*` (the shim that
# mimics phantom-agent's config.config interface so connector code
# imports unchanged).
COPY runtime /app/runtime
COPY config /app/config

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
# The runtime listens on this port; the agent's MCP proxy reaches
# the connector container at <container_hostname>:9000. Override
# at container start with -e PORT=... if needed.
ENV PORT=9000
EXPOSE 9000

# HEALTHCHECK — agent's MCP proxy + phantom-updater both poll
# /health to determine readiness.
#
# The check uses `python3 -c urllib.request.urlopen` rather than `wget`:
# `wget` is NOT in python:3.12-slim's Debian base image (the slim
# variant strips wget AND curl AND nc), so a wget-based HEALTHCHECK
# would error with exit 127 and report every container as unhealthy.
#
# Python is already in the container (this IS a Python container),
# so we use urllib.request to hit /health. The check exits 0 when
# urlopen succeeds (status 2xx), non-zero when it raises (network
# error, non-2xx, timeout). `|| exit 1` normalizes any unexpected
# exit code to 1 so docker sees a consistent failure signal.
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/health', timeout=3)" || exit 1

# The runtime entrypoint. Per-connector images can override CMD/ENTRYPOINT
# if they need pre-flight setup (e.g. `playwright install` for the web
# connector before the runtime starts), but the default just runs the
# entrypoint module.
ENTRYPOINT ["python", "-m", "runtime.entrypoint"]
