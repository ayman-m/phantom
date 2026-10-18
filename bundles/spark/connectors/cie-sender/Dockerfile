# phantom-connector-cie-sender: per-connector image for the cie-sender connector, built FROM phantom-connector-runtime.
# Adds no Python dependencies: httpx is already in the base.
#
# Build context is the repo root:
#   docker build -f bundles/spark/connectors/cie-sender/Dockerfile -t ghcr.io/ayman-m/phantom-connector-cie-sender-oss:0.1.0 .

ARG PHANTOM_RUNTIME_OWNER=ayman-m
ARG PHANTOM_RUNTIME_VERSION=latest
FROM ghcr.io/${PHANTOM_RUNTIME_OWNER}/phantom-connector-runtime-oss:${PHANTOM_RUNTIME_VERSION}

LABEL org.opencontainers.image.source="https://github.com/ayman-m/phantom"
LABEL org.opencontainers.image.description="Phantom cie-sender connector: provisions a synthetic directory into a Cloud Identity Engine SCIM directory."

COPY bundles/spark/connectors/cie-sender/src /app/connectors/cie-sender/src

ENV CONNECTOR_ID=cie-sender
