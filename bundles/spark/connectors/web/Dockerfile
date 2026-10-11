# phantom-connector-web — per-connector image for the headless-browser
# connector, built FROM phantom-connector-runtime.
#
# Extra Python deps:
#   - playwright: client lib only (NOT the bundled Chromium binaries —
#     those live in the phantom-browser sidecar). The connector calls
#     `chromium.connect_over_cdp(<sidecar-url>)`, which is bytes-level
#     CDP communication — the playwright lib speaks the protocol but
#     never spawns its own Chromium.
#   - trafilatura: readable-content extraction for `web.get_text` mode=
#     "readable" / "markdown". Pure Python (BSD-3, ~1MB), no native deps.
#
# Important: do NOT run `playwright install chromium` here. The
# connector's connect_over_cdp() path doesn't need a local Chromium;
# only the launch_chromium() path does, and the connector code never
# uses that. Skipping the install saves ~250MB of image size.

ARG PHANTOM_RUNTIME_OWNER=ayman-m
ARG PHANTOM_RUNTIME_VERSION=latest
FROM ghcr.io/${PHANTOM_RUNTIME_OWNER}/phantom-connector-runtime-oss:${PHANTOM_RUNTIME_VERSION}

LABEL org.opencontainers.image.source="https://github.com/ayman-m/phantom"
LABEL org.opencontainers.image.description="Phantom web connector container — headless-browser tools (navigate, get_text, screenshot, click, fill, etc.) running as a per-instance MCP server. Talks CDP to the phantom-browser sidecar."

# Connector-specific deps. Minimum versions match what the connector
# requires (see bundles/spark/mcp/requirements.txt:playwright,
# trafilatura).
RUN pip install --no-cache-dir \
    playwright>=1.48.0 \
    trafilatura>=2.0.0

COPY bundles/spark/connectors/web/src /app/connectors/web/src

ENV CONNECTOR_ID=web
