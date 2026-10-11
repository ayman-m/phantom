# phantom-connector-cortex-content — per-connector image for the Cortex
# Content marketplace fetch connector. Built FROM phantom-connector-runtime.
#
# Adds zero extra Python dependencies — the connector uses only stdlib
# (urllib, json, pathlib, time) plus httpx, and httpx is already in
# the base runtime image.
#
# The connector reads from a BAKED local catalog
# (bundles/spark/connectors/cortex-content/baked/), not live GitHub
# API calls. `_baked_client.py`'s `baked_root_path()` expects the
# catalog as a sibling of `src/` inside the connector's app
# directory; `_get_client()` raises FileNotFoundError if it's
# missing. Must be copied into the image explicitly — it is NOT
# pulled in by the `src/` COPY below.
#
# Why this connector is a per-instance container: every connector
# ships as container-style. Container isolation gives it the same
# crash + resource isolation guarantees as the other connectors, with
# no behavioral cost.

ARG PHANTOM_RUNTIME_OWNER=ayman-m
ARG PHANTOM_RUNTIME_VERSION=latest
FROM ghcr.io/${PHANTOM_RUNTIME_OWNER}/phantom-connector-runtime-oss:${PHANTOM_RUNTIME_VERSION}

LABEL org.opencontainers.image.source="https://github.com/ayman-m/phantom"
LABEL org.opencontainers.image.description="Phantom cortex-content connector container — Palo Alto Networks Cortex Content marketplace fetch (XSIAM packs, ModelingRules, ParsingRules, CorrelationRules) from the public demisto/content GitHub repository."

# No extra deps. httpx is in the base runtime image.

COPY bundles/spark/connectors/cortex-content/src /app/connectors/cortex-content/src
COPY bundles/spark/connectors/cortex-content/baked /app/connectors/cortex-content/baked

ENV CONNECTOR_ID=cortex-content
