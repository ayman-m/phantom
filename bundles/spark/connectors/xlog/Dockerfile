# phantom-connector-xlog — per-connector image for the xlog connector,
# built FROM phantom-connector-runtime.
#
# This image is what phantom-updater pulls + runs when an operator
# creates an xlog instance.
#
# What this image adds on top of phantom-connector-runtime:
#   - The xlog connector source (bundles/spark/connectors/xlog/src/)
#   - CONNECTOR_ID=xlog env var so the runtime entrypoint knows which
#     module to import
#
# What it does NOT add: extra Python deps. The xlog connector tools
# only call out to the xlog backend service (http://xlog:8000) via
# httpx, which is already in phantom-connector-runtime's requirements.

ARG PHANTOM_RUNTIME_OWNER=ayman-m
ARG PHANTOM_RUNTIME_VERSION=latest
FROM ghcr.io/${PHANTOM_RUNTIME_OWNER}/phantom-connector-runtime-oss:${PHANTOM_RUNTIME_VERSION}

LABEL org.opencontainers.image.source="https://github.com/ayman-m/phantom"
LABEL org.opencontainers.image.description="Phantom xlog connector container — synthetic log generation tools running as a per-instance MCP server."

# Connector source. Build context is the repo root so we can COPY
# from the bundle; the release build step uses the repo-root context
# (`docker build ... .`) for this image specifically.
COPY bundles/spark/connectors/xlog/src /app/connectors/xlog/src

# Tell the runtime entrypoint which connector to load. The entrypoint
# does `importlib.import_module(f"connectors.{CONNECTOR_ID}.src.connector")`
# at boot — this env-var resolves that path to the COPY above.
ENV CONNECTOR_ID=xlog

# ENTRYPOINT inherited from phantom-connector-runtime base
# (python -m runtime.entrypoint) — no override needed.
