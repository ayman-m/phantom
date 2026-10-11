# phantom-connector-cortex-docs — per-connector image for the Cortex
# public-documentation search/lookup connector. Built FROM
# phantom-connector-runtime.
#
# Adds zero extra Python dependencies — the upstream scripts use only
# stdlib (urllib, json, re, argparse, pathlib). The base runtime image
# already has httpx + pydantic which the embedded MCP needs to host the
# tool surface; the connector itself doesn't import either.
#
# cortex-docs runs as a per-instance container (`style: "container"` in
# connector.yaml; see docs/spec-per-instance-connector-containers.md),
# and its image is part of the digest-pinning manifest. Mirroring the
# xsiam/xlog/web/caldera Dockerfile pattern keeps the surface uniform.

ARG PHANTOM_RUNTIME_OWNER=ayman-m
ARG PHANTOM_RUNTIME_VERSION=latest
FROM ghcr.io/${PHANTOM_RUNTIME_OWNER}/phantom-connector-runtime-oss:${PHANTOM_RUNTIME_VERSION}

LABEL org.opencontainers.image.source="https://github.com/ayman-m/phantom"
LABEL org.opencontainers.image.description="Phantom cortex-docs connector container — Palo Alto Networks Cortex public-documentation search/lookup. Tools: cortex_search, cortex_suggest, cortex_xql_lookup, cortex_fetch_topic, cortex_fetch_toc, cortex_deep_research."

# No extra deps. The upstream scripts are stdlib-only.

COPY bundles/spark/connectors/cortex-docs/src /app/connectors/cortex-docs/src

ENV CONNECTOR_ID=cortex-docs
