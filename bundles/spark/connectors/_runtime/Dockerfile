# Reference Dockerfile for a container-style connector.
#
# Pattern (mirror this for your own connector):
#   1. ARG PHANTOM_RUNTIME_VERSION=latest
#   2. FROM ghcr.io/ayman-m/phantom-connector-runtime-oss:${PHANTOM_RUNTIME_VERSION}
#   3. (Optional) RUN pip install --no-cache-dir <connector-specific deps>
#   4. COPY <bundle-path>/src /app/connectors/<id>/src
#   5. ENV CONNECTOR_ID=<id>
#
# That's it. ENTRYPOINT + CMD + EXPOSE are inherited from the base.
#
# Build context = repo root, so the COPY can reach into bundles/.
# In the release pipeline: `docker build -f bundles/spark/connectors/<id>/Dockerfile .`

ARG PHANTOM_RUNTIME_VERSION=latest
FROM ghcr.io/ayman-m/phantom-connector-runtime-oss:${PHANTOM_RUNTIME_VERSION}

LABEL org.opencontainers.image.source="https://github.com/ayman-m/phantom"
LABEL org.opencontainers.image.description="Phantom reference connector skeleton (NOT a deployable connector — see bundles/spark/connectors/_runtime/README.md)."

# This skeleton has no extra deps. A real connector would add deps
# here, e.g.:
#   RUN pip install --no-cache-dir httpx>=0.27 google-auth>=2.30
# Each connector image carries its own deps so the base stays lean.

COPY bundles/spark/connectors/_runtime/src /app/connectors/_runtime/src

ENV CONNECTOR_ID=_runtime

# ENTRYPOINT inherited from phantom-connector-runtime: python -m runtime.entrypoint
