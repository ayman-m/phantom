# phantom-connector-xsiam — per-connector image for the XSIAM PAPI
# connector, built FROM phantom-connector-runtime.
#
# Adds google-auth as the only extra Python dep — needed because the
# XSIAM connector talks to Cortex PAPI through Google Vertex (some
# code paths) and to the PAPI surface directly with the operator's
# bearer (other code paths). The base image already has httpx +
# pydantic + cryptography which cover the rest of the surface.

ARG PHANTOM_RUNTIME_OWNER=ayman-m
ARG PHANTOM_RUNTIME_VERSION=latest
FROM ghcr.io/${PHANTOM_RUNTIME_OWNER}/phantom-connector-runtime-oss:${PHANTOM_RUNTIME_VERSION}

LABEL org.opencontainers.image.source="https://github.com/ayman-m/phantom"
LABEL org.opencontainers.image.description="Phantom xsiam connector container — Cortex XSIAM PAPI tools (XQL queries, dataset/asset/issue lookups, log push) running as a per-instance MCP server."

# Connector-specific deps. Pinned conservatively to match what the
# in-process connector uses today (bundles/spark/mcp/requirements.txt).
RUN pip install --no-cache-dir google-auth>=2.30.0

COPY bundles/spark/connectors/xsiam/src /app/connectors/xsiam/src

ENV CONNECTOR_ID=xsiam
