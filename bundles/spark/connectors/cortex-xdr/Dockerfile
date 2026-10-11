# phantom-connector-cortex-xdr — per-connector image for the
# Cortex XDR API wrapper. Built FROM phantom-connector-runtime.
#
# Wraps Cortex XDR's Public API for incident listing + XQL execution.
# Same auth pattern as XSIAM (Authorization + x-xdr-auth-id headers);
# uses uniform api_url / api_id / api_key config field names.
#
# Zero extra Python dependencies — only httpx, which is already in
# the phantom-connector-runtime base image. The connector's source
# is pure stdlib + httpx; no Mimikatz, no compiled binaries, no
# bundled payloads. Read-only against the upstream XDR API.

ARG PHANTOM_RUNTIME_OWNER=ayman-m
ARG PHANTOM_RUNTIME_VERSION=latest
FROM ghcr.io/${PHANTOM_RUNTIME_OWNER}/phantom-connector-runtime-oss:${PHANTOM_RUNTIME_VERSION}

LABEL org.opencontainers.image.source="https://github.com/ayman-m/phantom"
LABEL org.opencontainers.image.description="Phantom cortex-xdr connector container — Cortex XDR API wrapper. Tools: xdr_get_cases_and_issues, xdr_get_incident_extra_data, xdr_run_xql_query, xdr_get_xql_results."

# No extra deps. httpx + pydantic are in the base runtime.

COPY bundles/spark/connectors/cortex-xdr/src /app/connectors/cortex-xdr/src

ENV CONNECTOR_ID=cortex-xdr
