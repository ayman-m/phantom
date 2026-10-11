# phantom-connector-wec-sender: per-connector image for the wec-sender connector, built
# FROM phantom-connector-runtime. Adds no Python dependencies: the base already provides Python 3.12 and
# `cryptography`; the WS-Management client uses only the standard library.
#
# Build context is the repo root:
#   docker build -f bundles/spark/connectors/wec-sender/Dockerfile -t ghcr.io/ayman-m/phantom-connector-wec-sender-oss:0.1.2 .

ARG PHANTOM_RUNTIME_OWNER=ayman-m
ARG PHANTOM_RUNTIME_VERSION=latest
FROM ghcr.io/${PHANTOM_RUNTIME_OWNER}/phantom-connector-runtime-oss:${PHANTOM_RUNTIME_VERSION}

LABEL org.opencontainers.image.source="https://github.com/ayman-m/phantom"
LABEL org.opencontainers.image.description="Phantom wec-sender connector: forwards synthetic Windows events to a Cortex XSIAM Windows Event Collector over WS-Management."

COPY bundles/spark/connectors/wec-sender/src /app/connectors/wec-sender/src

ENV CONNECTOR_ID=wec-sender
