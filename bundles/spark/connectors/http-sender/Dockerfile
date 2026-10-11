# phantom-connector-http-sender: per-connector image for the http-sender connector, built
# FROM phantom-connector-runtime. Adds no Python dependencies: httpx is already in the base.
#
# Build context is the repo root:
#   docker build -f bundles/spark/connectors/http-sender/Dockerfile -t ghcr.io/ayman-m/phantom-connector-http-sender-oss:0.6.2 .

ARG PHANTOM_RUNTIME_OWNER=ayman-m
ARG PHANTOM_RUNTIME_VERSION=latest
FROM ghcr.io/${PHANTOM_RUNTIME_OWNER}/phantom-connector-runtime-oss:${PHANTOM_RUNTIME_VERSION}

LABEL org.opencontainers.image.source="https://github.com/ayman-m/phantom"
LABEL org.opencontainers.image.description="Phantom http-sender connector: sends JSON events for any data source to a Cortex XSIAM HTTP Log Collector or to the Cortex Cribl integration endpoint."

COPY bundles/spark/connectors/http-sender/src /app/connectors/http-sender/src

ENV CONNECTOR_ID=http-sender
